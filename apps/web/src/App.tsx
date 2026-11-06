import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  Activity, ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight,
  CircleHelp, Cloud, Code2, Download, ExternalLink, Flag, Github, Lock, LogOut,
  Pause, Play, RefreshCw, ShieldCheck, Sparkles, Target, Trophy, Users, XCircle, Coins,
} from 'lucide-react';
import { ApiError, downloadMaterials, request, watchEvaluation } from './api';
import type { Evaluation, Mission, Participant, ParticipantAuthResult, PublicEvent } from './api';
import './mission-lab.css';
import {isInstructorPath, loadSession, saveSession, clearSession} from './session';
import Playground from './Playground';
import MissionTimer,{type MissionClock} from './MissionTimer';
import HintShop,{type Hint} from './HintShop';

type View = 'home' | 'participant' | 'admin';
type Dashboard = {
  event: { event_id: string; title: string; status: string; active_mission_id: string; participation_mode: 'individual' | 'team' };
  team: { team_id: string; name: string; score: number; github_repo_name: string; github_repo_url: string; github_repo_link_awarded: boolean };
  missions: Mission[];
  evaluations: Evaluation[];
  mission_clock?:MissionClock;
  wallet?:{balance:number;earned:number;spent:number};
  hints?:Record<string,Hint[]>;
  evaluation_queue?: {waiting:number;running:number;execution_limit:number;admission_limit:number};
  github?: { available: boolean; authorized: boolean; login: string; install_url: string };
};
type LeaderboardRow = { rank: number; team_id: string; name: string; score: number; is_mine: boolean };
type AdminDashboard = {
  event: { event_id: string; title: string; status: string; active_mission_id: string; game_pack: string; participation_mode: 'individual' | 'team'; team_size: number; max_participants: number } | null;
  participants: number; submissions: number;
  mission_clock?:MissionClock;
  missions?:{id:string;title:string;duration_minutes:number}[];
  evaluation_queue?: {waiting:number;running:number;execution_limit:number;admission_limit:number};
  teams: { team_id: string; name: string; members: number; score: number; repo_url: string }[];
};

export default function App() {
  const instructorRoute = isInstructorPath(window.location.pathname);
  const [initialSession] = useState(() => loadSession(instructorRoute, localStorage, sessionStorage));
  const [view, setView] = useState<View>(instructorRoute ? 'admin' : 'home');
  const [token, setToken] = useState(initialSession.token);
  const [role, setRole] = useState(initialSession.role);
  const [participant, setParticipant] = useState<Participant | null>(() => {
    if (instructorRoute) return null;
    const value = localStorage.getItem('arena-participant'); return value ? JSON.parse(value) : null;
  });
  const [error, setError] = useState(new URLSearchParams(window.location.search).get('github')==='error' ? 'No se pudo autorizar GitHub. Instala la App en el repositorio vinculado y reintenta con su cuenta propietaria.' : '');
  const [notice, setNotice] = useState(new URLSearchParams(window.location.search).get('github')==='connected' ? 'Repositorio autorizado con GitHub. Ya puedes ejecutar el workflow de tu misión.' : '');
  const [busy, setBusy] = useState(false);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardRow[]>([]);
  const [adminData, setAdminData] = useState<AdminDashboard | null>(null);
  const [selectedMission, setSelectedMission] = useState<Mission | null>(null);
  const [answer, setAnswer] = useState('');
  const [githubRepoUrl, setGithubRepoUrl] = useState('');
  const initialQuery = new URLSearchParams(window.location.search);
  const [joinForm, setJoinForm] = useState({ event_code: initialQuery.get('event') || '', invite_code: initialQuery.get('invite') || '', display_name: '' });
  const [eventInfo, setEventInfo] = useState<PublicEvent | null>(null);
  const [registrationPath, setRegistrationPath] = useState<'create' | 'join'>(initialQuery.get('invite') ? 'join' : 'create');
  const [teamName, setTeamName] = useState('');
  const [teamInvite, setTeamInvite] = useState<{invite_code:string;invite_url:string;team_name:string} | null>(() => {
    if (instructorRoute) return null;
    const value = sessionStorage.getItem('arena-team-invite'); return value ? JSON.parse(value) : null;
  });
  const [adminForm, setAdminForm] = useState({ username: 'admin', password: '' });
  const [newEventTitle, setNewEventTitle] = useState('Todo empieza con un evento');
  const [newEventMode, setNewEventMode] = useState<'individual' | 'team'>('individual');
  const [newEventTeamSize, setNewEventTeamSize] = useState(5);
  const [newEventMaxParticipants, setNewEventMaxParticipants] = useState(50);
  const [missionDuration,setMissionDuration]=useState<number|''>('');
  const [clockExpired,setClockExpired]=useState(false);
  const [createdEvent, setCreatedEvent] = useState<{event_code:string;participation_mode:'individual'|'team';team_size:number;max_participants:number}|null>(null);

  const signedIn = Boolean(token && role);
  const currentMission = useMemo(() => dashboard?.missions.find(m => m.active) || dashboard?.missions.find(m => !m.completed), [dashboard]);
  const missionClosed=clockExpired||Boolean(dashboard?.mission_clock?.closed);
  useEffect(()=>setClockExpired(Boolean(dashboard?.mission_clock?.closed)),[dashboard?.event.active_mission_id,dashboard?.mission_clock?.deadline,dashboard?.mission_clock?.paused]);
  useEffect(()=>{if(dashboard)setSelectedMission(current=>dashboard.missions.find(m=>m.id===current?.id)||dashboard.missions.find(m=>m.active)||null);},[dashboard]);
  const pendingEvaluation = dashboard?.evaluations?.find(evaluation => ['pending', 'preparing', 'running'].includes(evaluation.status));
  const missionEvaluation = dashboard?.evaluations?.filter(evaluation => evaluation.mission_id === selectedMission?.id)
    .sort((a,b) => (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at))[0];
  const displayedEvaluation = pendingEvaluation || missionEvaluation;

  useEffect(() => {
    if (role !== 'participant' || !token || view !== 'participant') return;
    let loading = false;
    const timer = window.setInterval(async () => {
      if (loading || document.hidden) return;
      loading = true;
      try { await refreshParticipant(); }
      catch (e) { setError((e as Error).message); }
      finally { loading = false; }
    }, 6000 + Math.floor(Math.random() * 3000));
    return () => window.clearInterval(timer);
  }, [token, role, view]);

  useEffect(() => {
    if (!token || role !== 'participant' || !pendingEvaluation || pendingEvaluation.status==='pending') return;
    const controller = new AbortController();
    let timer: number | undefined;
    const connect = async () => {
      try {
        await watchEvaluation(pendingEvaluation.evaluation_id, token, controller.signal, value => {
          if (controller.signal.aborted) return;
          setDashboard(current => current ? {...current, evaluations: current.evaluations.map(item => item.evaluation_id === value.evaluation_id ? value : item)} : current);
          if (['passed', 'failed', 'blocked'].includes(value.status)) void refreshParticipant().catch(() => {});
        });
      } catch { /* Periodic dashboard refresh remains available during reconnection. */ }
      if (!controller.signal.aborted) timer = window.setTimeout(connect, 2000);
    };
    void connect();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [token, role, pendingEvaluation?.evaluation_id, pendingEvaluation?.status]);

  function persistSession(newToken: string, newRole: string, p?: Participant) {
    saveSession(instructorRoute, newToken, newRole, localStorage, sessionStorage);
    setToken(newToken); setRole(newRole);
    if (p && newRole === 'participant') { setParticipant(p); localStorage.setItem('arena-participant', JSON.stringify(p)); }
  }
  function logout() {
    setToken(''); setRole(''); setParticipant(null); setDashboard(null); setAdminData(null); setView(instructorRoute ? 'admin' : 'home');
    clearSession(instructorRoute, localStorage, sessionStorage);
    if (!instructorRoute) setTeamInvite(null);
  }
  async function refreshParticipant() {
    if (!token) return;
    const [d, l] = await Promise.all([
      request<Dashboard>('/api/v1/participant/dashboard', token),
      request<{ leaderboard: LeaderboardRow[] }>('/api/v1/leaderboard', token),
    ]);
    setDashboard(d); setLeaderboard(l.leaderboard); setGithubRepoUrl(d.team.github_repo_url || '');
  }
  async function refreshAdmin() {
    if (!token) return;
    setAdminData(await request<AdminDashboard>('/api/v1/admin/dashboard', token));
  }
  useEffect(() => {
    if (!signedIn) return;
    const load = async () => {
      try { if (instructorRoute && role === 'admin') { setView('admin'); await refreshAdmin(); } else { setView('participant'); await refreshParticipant(); } }
      catch (e) {
        if (instructorRoute && e instanceof ApiError && [401, 403].includes(e.status)) {
          clearSession(true, localStorage, sessionStorage);
          setToken(''); setRole(''); setView('admin');
          setError('Tu sesión de instructor terminó. Vuelve a iniciar sesión.');
        } else setError((e as Error).message);
      }
    };
    load();
    // Participant refresh discovers deliveries requested from GitHub Actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role]);

  async function lookupEvent(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice(''); setEventInfo(null);
    try {
      const code = joinForm.event_code.trim().toUpperCase();
      const result = await request<PublicEvent>(`/api/v1/public/events/${encodeURIComponent(code)}`);
      setEventInfo(result);
      if (result.participation_mode === 'individual') setRegistrationPath('create');
      else if (joinForm.invite_code) setRegistrationPath('join');
      setJoinForm(current => ({ ...current, event_code: code }));
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function enterParticipantArena(result: ParticipantAuthResult, message = '¡Bienvenido a la Arena!') {
    persistSession(result.access_token, 'participant', result.participant);
    setView('participant'); setNotice(message); setError(''); setEventInfo(null);
    if (result.invite_code && result.invite_url) {
      const invite = { invite_code: result.invite_code, invite_url: result.invite_url, team_name: result.participant.team_name };
      setTeamInvite(invite); sessionStorage.setItem('arena-team-invite', JSON.stringify(invite));
    }
    const [d,l] = await Promise.all([
      request<Dashboard>('/api/v1/participant/dashboard', result.access_token),
      request<{leaderboard:LeaderboardRow[]}>('/api/v1/leaderboard', result.access_token),
    ]);
    setDashboard(d); setLeaderboard(l.leaderboard); setGithubRepoUrl(d.team.github_repo_url || '');
  }
  async function join(e: FormEvent) {
    e.preventDefault(); if (!eventInfo) { setError('Primero consulta el código del evento.'); return; }
    setBusy(true); setError('');
    try {
      const payload = eventInfo.participation_mode === 'individual'
        ? { event_code: eventInfo.event_code, display_name: joinForm.display_name }
        : { event_code: eventInfo.event_code, display_name: joinForm.display_name, invite_code: joinForm.invite_code };
      const result = await request<ParticipantAuthResult>('/api/v1/auth/join', undefined, { method:'POST', body:JSON.stringify(payload) });
      await enterParticipantArena(result);
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function createTeam(e: FormEvent) {
    e.preventDefault(); if (!eventInfo) return; setBusy(true); setError('');
    try {
      const result = await request<ParticipantAuthResult>('/api/v1/auth/create-team', undefined, { method:'POST', body:JSON.stringify({event_code:eventInfo.event_code, display_name:joinForm.display_name, team_name:teamName}) });
      await enterParticipantArena(result, 'Equipo creado. Comparte la invitación con tus compañeros.');
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function copyTeamInvite() {
    if (!teamInvite) return;
    const link = new URL(teamInvite.invite_url, window.location.origin).toString();
    try { await navigator.clipboard.writeText(link); setNotice('Enlace de invitación copiado.'); }
    catch { setNotice(`No se pudo copiar automáticamente. Selecciona el enlace o comparte el código: ${teamInvite.invite_code}`); }
  }
  async function adminLogin(e: FormEvent) {
    e.preventDefault();
    if (!instructorRoute) return; setBusy(true); setError('');
    try {
      const result = await request<{access_token:string}>('/api/v1/auth/admin/login', undefined, { method:'POST', body:JSON.stringify(adminForm) });
      persistSession(result.access_token, 'admin'); setView('admin');
      setAdminData(await request<AdminDashboard>('/api/v1/admin/dashboard', result.access_token));
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function submitAnswer(e: FormEvent) {
    e.preventDefault(); if (!selectedMission) return; setBusy(true); setError(''); setNotice('');
    try {
      const result = await request<{passed:boolean; points:number; message:string}>(`/api/v1/participant/missions/${selectedMission.id}/answer`, token, {method:'POST',body:JSON.stringify({answer})});
      if (result.passed) { setNotice(`${result.message} +${result.points} puntos`); setSelectedMission(null); setAnswer(''); await refreshParticipant(); }
      else setError(result.message);
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function connectGithubRepository(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const result = await request<{repo_name:string;repo_url:string;awarded:boolean;points:number}>(
        '/api/v1/participant/github-repository',
        token,
        {method:'POST',body:JSON.stringify({repo_url:githubRepoUrl})},
      );
      setGithubRepoUrl(result.repo_url);
      setNotice(result.awarded ? `Repositorio vinculado. +${result.points} punto.` : 'Este repositorio ya estaba vinculado al equipo.');
      await refreshParticipant();
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function authorizeGithub() {
    setBusy(true); setError('');
    try {
      const result = await request<{url:string}>('/api/v1/participant/github/authorize',token,{method:'POST'});
      window.location.assign(result.url);
    } catch(e) { setError((e as Error).message); setBusy(false); }
  }
  async function downloadMissionKit() {
    if (!selectedMission?.materials) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const blob = await downloadMaterials(selectedMission.id, token);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = selectedMission.materials.filename;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('Kit descargado. Descomprímelo y sigue README.md para subirlo a GitHub.');
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function adminStatus(status: string) {
    if (!adminData?.event) return; setBusy(true); setError('');
    try { await request(`/api/v1/admin/events/${adminData.event.event_id}/status`, token, {method:'PATCH',body:JSON.stringify({status})}); await refreshAdmin(); setNotice(`Evento ${status}`); }
    catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function activateMission(mission_id: string) {
    if (!adminData?.event) return; setBusy(true); setError('');
    try { await request(`/api/v1/admin/events/${adminData.event.event_id}/activate-mission`, token, {method:'POST',body:JSON.stringify({mission_id,...(missionDuration?{duration_minutes:missionDuration}:{})})}); await refreshAdmin(); setNotice(`Misión activada: ${mission_id}. El reloj comienza ahora.`); }
    catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function createEvent(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setCreatedEvent(null);
    try {
      const result = await request<{event_id:string;event_code:string;participation_mode:'individual'|'team';team_size:number;max_participants:number}>('/api/v1/admin/events', token, {method:'POST',body:JSON.stringify({title:newEventTitle,game_pack:'aws-event-driven',participation_mode:newEventMode,team_size:newEventTeamSize,max_participants:newEventMaxParticipants})});
      setCreatedEvent({event_code:result.event_code,participation_mode:result.participation_mode,team_size:result.team_size,max_participants:result.max_participants});
      await refreshAdmin(); setNotice('Evento creado. Ya puedes compartir el código del evento.');
    } catch(e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return <div className="app-shell">
    <header className="topbar">
      <button className="brand" onClick={() => setView(instructorRoute ? 'admin' : signedIn ? 'participant' : 'home')}>
        <span className="brand-mark"><Cloud size={21}/></span><span>CloudOps <b>Arena</b></span>
      </button>
      <div className="top-actions">
        <span className="env-pill"><span className="pulse"/> CLOUDOPS ARENA</span>
        {signedIn && <button className="icon-button" title="Cerrar sesión" onClick={logout}><LogOut size={17}/></button>}
      </div>
    </header>

    <main className="main-wrap">
      {error && <div className="alert error"><XCircle size={17}/><span>{error}</span><button onClick={()=>setError('')}><XCircle size={15}/></button></div>}
      {notice && <div className="alert success"><CheckCircle2 size={17}/><span>{notice}</span><button onClick={()=>setNotice('')}><XCircle size={15}/></button></div>}

      {!instructorRoute && view === 'home' && <section className="hero-grid">
        <div className="hero-copy">
          <div className="eyebrow"><Sparkles size={14}/> LEARN BY BUILDING</div>
          <h1>Aprende.<br/><span>Construye.</span><br/>Supérate.</h1>
          <p className="hero-lead">Experiencias prácticas de ingeniería, cloud y DevOps. Aprende resolviendo desafíos reales con tu equipo.</p>
          <div className="hero-tags"><span>AWS</span><span>Terraform</span><span>Event-Driven</span><span>CI/CD</span></div>
        </div>
        <div className="entry-card">
          <div className="card-heading"><div><div className="eyebrow">PARTICIPANT ACCESS</div><h2>Entra a la Arena</h2></div><Users size={22}/></div>
          <form onSubmit={lookupEvent} className="form-stack">
            <label>Tu nombre<input required minLength={2} maxLength={60} value={joinForm.display_name} onChange={e=>setJoinForm({...joinForm,display_name:e.target.value})} placeholder="Ej. Andrea Pérez"/></label>
            <label>Código del evento<input required minLength={4} maxLength={64} value={joinForm.event_code} onChange={e=>{setJoinForm({...joinForm,event_code:e.target.value});setEventInfo(null);}} placeholder="Ej. ARENA-8F31A2BC"/></label>
            <button className="primary-button" disabled={busy || joinForm.display_name.trim().length<2 || joinForm.event_code.trim().length<4}>{busy?'Consultando…':'Continuar'} <ArrowRight size={17}/></button>
          </form>
          {eventInfo && <div className="registration-next">
            <div className="event-summary"><span className="event-summary-label">EVENTO DISPONIBLE</span><b>{eventInfo.title}</b><small>{eventInfo.participation_mode==='individual'?'Participación individual':`Equipos de hasta ${eventInfo.team_size} integrantes`} · Máximo {eventInfo.max_participants} participantes</small></div>
            {eventInfo.participation_mode==='individual' ? <form onSubmit={join} className="form-stack"><div className="registration-note">Tu inscripción será individual. Tendrás tu propio progreso y posición en el marcador.</div><button className="primary-button" disabled={busy}>{busy?'Registrando…':'Registrarme'} <ArrowRight size={17}/></button></form> : <>
              <div className="registration-tabs"><button type="button" className={registrationPath==='create'?'selected':''} onClick={()=>setRegistrationPath('create')}>Crear equipo</button><button type="button" className={registrationPath==='join'?'selected':''} onClick={()=>setRegistrationPath('join')}>Tengo invitación</button></div>
              {registrationPath==='create' ? <form onSubmit={createTeam} className="form-stack"><label>Nombre del equipo<input required minLength={2} maxLength={60} value={teamName} onChange={e=>setTeamName(e.target.value)} placeholder="Ej. Lambda Force"/></label><div className="registration-note">Serás el líder y recibirás un enlace/código para invitar a tus compañeros. Tu registro cuenta como el primer integrante.</div><button className="primary-button" disabled={busy || !teamName.trim()}>{busy?'Creando equipo…':'Crear equipo y entrar'} <ArrowRight size={17}/></button></form> : <form onSubmit={join} className="form-stack"><label>Código de invitación<input required minLength={6} maxLength={80} value={joinForm.invite_code} onChange={e=>setJoinForm({...joinForm,invite_code:e.target.value.toUpperCase()})} placeholder="Pide el código al líder del equipo"/></label><div className="registration-note">Si recibiste un enlace de invitación, el código se habrá completado automáticamente.</div><button className="primary-button" disabled={busy || !joinForm.invite_code.trim()}>{busy?'Ingresando…':'Unirme al equipo'} <ArrowRight size={17}/></button></form>}
            </>}
          </div>}
          <div className="card-foot"><Lock size={13}/> {eventInfo?.participation_mode==='team'?'El líder comparte la invitación con su equipo':'Registro mediante código del evento'}</div>
        </div>
        <div className="hero-stats"><div><b>01</b><span>Construye</span></div><div><b>02</b><span>Automatiza</span></div><div><b>03</b><span>Resuelve</span></div></div>
      </section>}

      {instructorRoute && view === 'admin' && !signedIn && <section className="auth-panel narrow">
        <div className="panel-icon"><ShieldCheck size={25}/></div><div className="eyebrow">INSTRUCTOR CONSOLE</div><h2>Panel del instructor</h2><p>Administra la partida, activa misiones y consulta el avance de los equipos.</p>
        <form onSubmit={adminLogin} className="form-stack">
          <label>Usuario<input value={adminForm.username} onChange={e=>setAdminForm({...adminForm,username:e.target.value})}/></label>
          <label>Contraseña<input type="password" value={adminForm.password} onChange={e=>setAdminForm({...adminForm,password:e.target.value})}/></label>
          <button className="primary-button" disabled={busy}>{busy?'Ingresando…':'Entrar al panel'} <ArrowRight size={17}/></button>
        </form>
        <a className="text-button" href="/">Volver al portal de participantes</a>
      </section>}

      {!instructorRoute && view === 'participant' && role === 'participant' && dashboard && <>
        <section className="welcome-row">
          <div><div className="eyebrow">TU LABORATORIO · {dashboard.event.participation_mode==='team'?'EN EQUIPO':'INDIVIDUAL'}</div><h1>¡Vamos, {participant?.name || 'equipo'}!</h1><p>{dashboard.event.participation_mode==='team'?'Tu equipo es':'Tu espacio individual es'} <b>{dashboard.team.name}</b>. Completa misiones para sumar puntos.</p></div>
          <div className="score-card"><Trophy size={21}/><div><b>{dashboard.team.score}</b><span>puntos</span></div></div>
        </section>
        {pendingEvaluation?.status==='pending' && <div className="evaluation-pending" role="status"><b>Tu entrega está en cola</b><span>{pendingEvaluation.queue_position ? `Posición ${pendingEvaluation.queue_position} en este evento · ${pendingEvaluation.queue_total} esperando.` : 'Esperando un cupo disponible.'} Puedes seguir revisando las instrucciones; no necesitas volver a enviarla.</span></div>}
        {participant?.is_team_leader && teamInvite && <div className="side-card team-invite-card"><div className="section-heading"><h3><Users size={17}/> Invita a tu equipo</h3><button className="secondary-button" onClick={copyTeamInvite}>Copiar enlace</button></div><p>Comparte este enlace con tus compañeros para que se registren directamente en <b>{teamInvite.team_name}</b>.</p><input className="invite-link" aria-label="Enlace de invitación" readOnly value={new URL(teamInvite.invite_url, window.location.origin).toString()} onFocus={e=>e.currentTarget.select()}/><div className="invite-code">{teamInvite.invite_code}</div><p className="muted-note">El código solo se muestra al líder. Guárdalo antes de cerrar esta sesión.</p></div>}
        <section className="lab-mission-control">
          <div className="lab-focus"><span className="eyebrow">TU SIGUIENTE RETO</span><h2>{currentMission?.title||'¡Misiones completadas!'}</h2><p>{missionClosed?'El tiempo terminó. Puedes revisar tu trabajo mientras el instructor abre la siguiente misión.':currentMission?.description}</p><div className="lab-focus-meta"><button className="primary-button" onClick={()=>{if(currentMission)setSelectedMission(currentMission);window.setTimeout(()=>document.getElementById('mission-workspace')?.scrollIntoView({behavior:'smooth',block:'start'}),0);}}>{missionClosed?'Revisar misión':'Continuar misión'}<ArrowRight size={16}/></button><span>{dashboard.missions.filter(m=>m.completed).length} / {dashboard.missions.length} misiones completadas</span><span className="coin-badge"><Coins size={17}/>{dashboard.wallet?.balance||0} monedas</span></div></div>
          <MissionTimer clock={dashboard.mission_clock} onClosed={()=>setClockExpired(true)}/>
        </section>
        <div className="lab-journey" aria-label="Recorrido del laboratorio">{['Conecta tu repositorio','Valida tu plan','Despliega en Actions','Explora tu infraestructura'].map((step,index)=><div key={step}><span>{String(index+1).padStart(2,'0')}</span><b>{step}</b>{index<3&&<ChevronRight size={16}/>}</div>)}</div>
        <Playground key={token} token={token} eventStatus={dashboard.event.status}/>
        <section className="content-grid">
          <div className="main-column">
            <div className="section-heading"><div><div className="eyebrow">RUTA DE MISIONES</div><h2>{dashboard.event.title}</h2></div><button className="icon-button" onClick={()=>refreshParticipant()}><RefreshCw size={16}/></button></div>
            <div className="mission-list">
              {dashboard.missions.map((m,i)=><button key={m.id} className={`mission-card ${m.active?'active':''} ${m.completed?'complete':''} ${m.locked?'locked':''}`} onClick={()=>{setSelectedMission(m);setAnswer('');}} disabled={m.locked}>
                <div className="mission-num">{m.completed?<Check size={18}/>:String(i+1).padStart(2,'0')}</div>
                <div className="mission-info"><div className="mission-meta"><span>{m.category.toUpperCase()}</span><span>{m.duration_minutes} MIN</span></div><h3>{m.title}</h3><p>{m.description}</p></div>
                <div className="mission-points">{m.completed?<CheckCircle2 size={19}/>:<><b>{m.points}</b><small>PTS</small></>}</div>
              </button>)}
            </div>
            {selectedMission && <div className="mission-detail" id="mission-workspace">
              <div className="detail-head"><div><div className="eyebrow">MISSION BRIEFING</div><h3>{selectedMission.title}</h3></div><button className="icon-button" onClick={()=>setSelectedMission(null)}><XCircle size={18}/></button></div>
              <p>{selectedMission.description}</p>
              <ol>{selectedMission.instructions?.map((step,i)=><li key={i}>{step}</li>)}</ol>
              {selectedMission.materials && <section className="lab-materials">
                <div className="lab-step-heading"><Download size={17}/><div><h4>Materiales del laboratorio</h4><p>{selectedMission.materials.title}. Incluye la estructura del proyecto y una guía para trabajar desde el navegador.</p></div></div>
                <button className="primary-button" onClick={downloadMissionKit} disabled={busy}><Download size={16}/>{busy?'Preparando descarga…':'Descargar kit inicial (.zip)'}</button>
                <ol>{selectedMission.materials.instructions.map((instruction,index)=><li key={index}>{instruction}</li>)}</ol>
                <p className="muted-note">El kit incluye ejercicios pendientes. Descargarlo no completa la misión ni concede puntos.</p>
              </section>}
              {selectedMission.resources && <section className="lab-resources">
                <h4>Recursos previstos del laboratorio</h4>
                <div className="lab-resource-list">{selectedMission.resources.map(resource=><div className="lab-resource" key={resource.name}><b>{resource.name}</b><span>{resource.purpose}</span></div>)}</div>
              </section>}
              {selectedMission.id==='mission-02' && <section className="lab-repository">
                <div className="lab-step-heading"><Github size={17}/><div><h4>1. Vincula el repositorio de tu equipo</h4><p>El repositorio debe existir en GitHub y contener el laboratorio y el workflow indicado arriba.</p></div></div>
                {dashboard.team.github_repo_url && <div className="lab-repository-connected"><CheckCircle2 size={17}/><span>Repositorio vinculado: <a href={dashboard.team.github_repo_url} target="_blank" rel="noreferrer">{dashboard.team.github_repo_name || dashboard.team.github_repo_url}<ExternalLink size={13}/></a></span></div>}
                {dashboard.team.github_repo_url && <div className="github-authorization">
                  {dashboard.github?.authorized ? <p>Acceso autorizado por <b>{dashboard.github.login}</b>.</p> : dashboard.github?.available ? <>
                    <p>Instala la App seleccionando este repositorio. Después autorízalo con la cuenta de GitHub propietaria.</p>
                    <a href={dashboard.github.install_url} target="_blank" rel="noreferrer">1. Instalar GitHub App <ExternalLink size={13}/></a>
                    <button className="small-button" disabled={busy || dashboard.event.status!=='open'} onClick={authorizeGithub}>2. Autorizar mi repositorio</button>
                  </> : <p className="muted-note">La autorización de GitHub estará disponible cuando el instructor termine de configurar la App.</p>}
                </div>}
                {!dashboard.team.github_repo_link_awarded && <form onSubmit={connectGithubRepository} className="form-stack">
                  <label>{dashboard.team.github_repo_url?'Confirma el repositorio vinculado':'URL HTTPS del repositorio'}<input type="url" required minLength={19} maxLength={250} value={githubRepoUrl} onChange={event=>setGithubRepoUrl(event.target.value)} placeholder="https://github.com/organizacion/repositorio" readOnly={Boolean(dashboard.team.github_repo_url)}/></label>
                  <button className="primary-button" disabled={busy || missionClosed || !githubRepoUrl.trim()}>{busy?'Vinculando…':`${dashboard.team.github_repo_url?'Confirmar repositorio':'Vincular repositorio'} · +${selectedMission.repository_link_points ?? 1} punto`} <ArrowRight size={16}/></button>
                </form>}
                <div className="lab-repository-points">Puntaje de la misión: {selectedMission.repository_link_points ?? 1} punto por vincular el repositorio + {selectedMission.points - (selectedMission.repository_link_points ?? 1)} puntos por superar la validación técnica oficial. La aprobación del evaluador oficial concede esos puntos; encontrar archivos o completar un workflow por sí solo no los concede.</div>
              </section>}
              {selectedMission.quiz && <form onSubmit={submitAnswer} className="quiz-form"><b>{selectedMission.quiz.question}</b>{selectedMission.quiz.options.map(option=><label className={`option ${answer===option?'chosen':''}`} key={option}><input type="radio" name="answer" value={option} checked={answer===option} onChange={()=>setAnswer(option)}/>{option}</label>)}<button className="primary-button" disabled={!answer||busy||missionClosed||!selectedMission.active||dashboard.event.status!=='open'}>{missionClosed?'Tiempo agotado':'Enviar respuesta'} <ArrowRight size={16}/></button></form>}
              <HintShop key={token+selectedMission.id} token={token} mission={selectedMission.id} hints={dashboard.hints?.[selectedMission.id]||[]} balance={dashboard.wallet?.balance||0} closed={missionClosed||!selectedMission.active||dashboard.event.status!=='open'} onChanged={refreshParticipant}/>
              {selectedMission.workflow && <section className="lab-repository">
                <div className="lab-step-heading"><Code2 size={17}/><div><h4>Solicita la evaluación de tu entrega</h4><p>Guarda tus cambios en GitHub y ejecuta el workflow de esta misión desde Actions.</p></div></div>
                {displayedEvaluation && <div className="evaluation-pending" role="status">
                  <b>{displayedEvaluation.status==='passed' && displayedEvaluation.operation==='plan' ? 'Plan validado · falta desplegar' : {pending:'Entrega pendiente', preparing:'Revisando entrega', running:'Evaluando la misión', passed:'Entrega aprobada', failed:'Entrega con errores', blocked:'Evaluación bloqueada'}[displayedEvaluation.status]} · {displayedEvaluation.mission_id}</b>
                  <span>{displayedEvaluation.repo_name} · <code>{displayedEvaluation.commit_sha}</code></span>
                  {displayedEvaluation.status==='pending' && displayedEvaluation.queue_position && <span>Posición {displayedEvaluation.queue_position} en la cola de este evento · {displayedEvaluation.queue_total} esperando. Tu entrega está guardada; no necesitas enviarla otra vez.</span>}
                  <span>{displayedEvaluation.message || 'Esperando la revisión automática del repositorio.'}</span>
                  {displayedEvaluation.source==='github-actions' && <a href={displayedEvaluation.actions_url} target="_blank" rel="noreferrer">Ver ejecución en GitHub Actions <ExternalLink size={13}/></a>}
                  {!!displayedEvaluation.progress?.length && <ol className="evaluation-progress" aria-label="Etapas de evaluación">{displayedEvaluation.progress.filter((stage,index,all)=>!all.slice(index+1).some(next=>next.stage===stage.stage)).map(stage=><li key={stage.stage} data-status={stage.status}><span>{stage.status==='passed'?'✓':stage.status==='failed'?'×':'◌'}</span> {stage.message} <small>{stage.status==='running'?'En curso':stage.status==='passed'?'Completado':'Con errores'}</small></li>)}</ol>}
                  {displayedEvaluation.missing_files && <ul>{displayedEvaluation.missing_files.map(path=><li key={path}><code>{path}</code></li>)}</ul>}
                  <span>Solicitud {displayedEvaluation.evaluation_id} · Intento {displayedEvaluation.attempt || 1}.{displayedEvaluation.status==='passed' ? ` +${displayedEvaluation.points_awarded || 0} puntos.` : ' Solo una validación técnica aprobada concede puntos.'}</span>
                </div>}
                {selectedMission.materials && <div className="actions-setup"><b>Entregas con GitHub Actions</b><p>Usa el workflow del kit actualizado y crea la variable de repositorio <code>ARENA_EVENT_ID</code> con este valor:</p><code>{dashboard.event.event_id}</code><p>Al guardar cambios en la rama predeterminada, Actions solicitará la revisión. Aquí aparecerán sus etapas y resultado. Autoriza primero el repositorio con la GitHub App.</p></div>}
                <p className="muted-note">Las entregas se envían desde GitHub Actions. Para reintentar un commit fallido o bloqueado, abre Run workflow y activa retry. Las misiones aprobadas no vuelven a sumar puntos.</p>
              </section>}
              {!selectedMission.quiz && !selectedMission.workflow && <div className="hint-box"><BookOpen size={17}/><span>Esta misión requiere validación técnica. Sigue las instrucciones del instructor.</span></div>}
            </div>}
          </div>
          <aside className="side-column">
            <div className="side-card"><div className="section-heading"><h3><Trophy size={17}/> {dashboard.event.participation_mode==='team'?'Leaderboard de equipos':'Leaderboard individual'}</h3><button className="icon-button" onClick={()=>refreshParticipant()}><RefreshCw size={14}/></button></div>
              {leaderboard.slice(0,10).map(row=><div className={`rank-row ${row.is_mine?'mine':''}`} key={row.team_id}><span className="rank-num">{row.rank===1?'🏆':row.rank}</span><span className="rank-name">{row.name}{row.is_mine&&<small>{dashboard.event.participation_mode==='team'?' TU EQUIPO':' TÚ'}</small>}</span><b>{row.score}</b></div>)}
            </div>
            <div className="side-card tips"><div className="eyebrow">RECUERDA</div><h3>¿Te atascaste? Hay una pista.</h3><p>Completa misiones para ganar monedas. En el centro de pistas puedes comprar orientaciones sin reducir tu puntuación. Revisa también el resultado de tu entrega en Actions.</p><div className="tip-icon"><Target size={21}/></div></div>
          </aside>
        </section>
      </>}

      {instructorRoute && view === 'admin' && role === 'admin' && adminData && <>
        <section className="welcome-row"><div><div className="eyebrow">INSTRUCTOR CONSOLE</div><h1>Control de la Arena</h1><p>{adminData.event?.title || 'Sin evento configurado'}</p></div><button className="secondary-button" onClick={()=>refreshAdmin()}><RefreshCw size={16}/> Actualizar</button></section>
        {!adminData.event && <div className="side-card event-create"><h3>Crear una nueva experiencia</h3><p>Define si los participantes trabajarán individualmente o crearán equipos.</p><form className="form-stack" onSubmit={createEvent}><label>Nombre del evento<input value={newEventTitle} onChange={e=>setNewEventTitle(e.target.value)} minLength={4} maxLength={100}/></label><label>Modalidad del laboratorio<select value={newEventMode} onChange={e=>setNewEventMode(e.target.value as 'individual'|'team')}><option value="team">Por equipos</option><option value="individual">Individual</option></select></label>{newEventMode==='team' && <label>Integrantes por equipo<input type="number" min="2" max="6" value={newEventTeamSize} onChange={e=>setNewEventTeamSize(Number(e.target.value))}/></label>}<label>Cupo máximo de participantes<input type="number" min="1" max="500" value={newEventMaxParticipants} onChange={e=>setNewEventMaxParticipants(Number(e.target.value))}/></label><button className="primary-button" disabled={busy}>Crear evento <ArrowRight size={16}/></button></form></div>}
        {createdEvent && <div className="side-card created-event-card"><h3>Evento creado correctamente</h3><p>Comparte este código con los participantes:</p><div className="invite-code">{createdEvent.event_code}</div><p className="muted-note">Modalidad: <b>{createdEvent.participation_mode==='team'?`Equipos de ${createdEvent.team_size}`:'Individual'}</b> · Cupo: <b>{createdEvent.max_participants}</b>. {createdEvent.participation_mode==='team'?'Cada líder creará su equipo y compartirá su propio enlace de invitación.':'Cada participante tendrá un registro y marcador individual.'}</p></div>}
        {adminData.event && <>
          <div className="admin-stats"><div className="stat-card"><Users/><b>{adminData.participants}</b><span>Participantes</span></div><div className="stat-card"><Flag/><b>{adminData.teams.length}</b><span>{adminData.event.participation_mode==='team'?'Equipos':'Registros individuales'}</span></div><div className="stat-card"><CheckCircle2/><b>{adminData.submissions}</b><span>Misiones validadas</span></div><div className="stat-card"><Activity/><b>{adminData.event.status}</b><span>Estado del evento</span></div></div>
          {adminData.evaluation_queue && <div className="side-card"><b>Cola de evaluaciones del evento</b><p>{adminData.evaluation_queue.waiting} esperando · {adminData.evaluation_queue.running} en preparación o ejecución · máximo {adminData.evaluation_queue.execution_limit} ejecuciones compartidas. Límite global: {adminData.evaluation_queue.admission_limit} entregas admitidas.</p></div>}
          <section className="admin-grid">
            <div className="side-card"><div className="section-heading"><h3>Control de partida</h3></div><div className="control-row"><span>Estado</span><div className="inline-actions"><button className="small-button" onClick={()=>adminStatus('open')}><Play size={14}/> Abrir</button><button className="small-button" onClick={()=>adminStatus('paused')}><Pause size={14}/> Pausar</button><button className="small-button danger" onClick={()=>adminStatus('finished')}><Flag size={14}/> Finalizar</button></div></div><div className="control-row"><span>Misión activa</span><b>{adminData.event.active_mission_id}</b></div>
              <label className="timer-config">Duración al activar (minutos)<input type="number" min="1" max="240" value={missionDuration} placeholder="Duración del Game Pack" onChange={e=>setMissionDuration(e.target.value?Number(e.target.value):'')}/><small>Activar o reiniciar comienza un reloj nuevo. Pausar el evento congela el tiempo.</small></label><MissionTimer clock={adminData.mission_clock}/><div className="mission-activation">{(adminData.missions||[]).map((mission,i)=><button key={mission.id} className={`small-button ${adminData.event?.active_mission_id===mission.id?'selected':''}`} onClick={()=>activateMission(mission.id)} title={mission.title}>{String(i+1).padStart(2,'0')} · {adminData.event?.active_mission_id===mission.id?'Reiniciar':'Activar'}</button>)}</div>
            </div>
            <div className="side-card"><div className="section-heading"><h3><Trophy size={17}/> Clasificación</h3></div><div className="team-table">{adminData.teams.map((team,i)=><div className="team-table-row" key={team.team_id}><span>#{i+1}</span><b>{team.name}</b><span>{team.members}/{adminData.event?.participation_mode==='team'?(adminData.event?.team_size ?? 5):1}</span><strong>{team.score} pts</strong></div>)}</div><p className="muted-note">La puntuación proviene de evidencias verificadas. Las monedas se obtienen al completar misiones y no alteran el ranking.</p></div>
          </section>
        </>}
        {adminData.event && <div className="side-card event-create"><h3>Crear otra partida</h3><form className="form-stack" onSubmit={createEvent}><label>Nombre del evento<input value={newEventTitle} onChange={e=>setNewEventTitle(e.target.value)} minLength={4} maxLength={100}/></label><label>Modalidad del laboratorio<select value={newEventMode} onChange={e=>setNewEventMode(e.target.value as 'individual'|'team')}><option value="team">Por equipos</option><option value="individual">Individual</option></select></label>{newEventMode==='team' && <label>Integrantes por equipo<input type="number" min="2" max="6" value={newEventTeamSize} onChange={e=>setNewEventTeamSize(Number(e.target.value))}/></label>}<label>Cupo máximo de participantes<input type="number" min="1" max="500" value={newEventMaxParticipants} onChange={e=>setNewEventMaxParticipants(Number(e.target.value))}/></label><button className="secondary-button" disabled={busy}>Crear nueva partida</button></form></div>}
      </>}
    </main>
    <footer className="footer"><span>CloudOps Arena <b>·</b> GameDay platform</span><span>Learn by building.</span></footer>
  </div>;
}
