import {useEffect,useState} from 'react';
import {Maximize, Trophy} from 'lucide-react';
import {ApiError,request} from './api';
export type ScreenData={title:string;status:string;participation_mode:string;mission:string|null;updated_at:string;leaderboard:{rank:number;name:string;score:number}[]};
export function ScreenTable({data}:{data:ScreenData}) {
 return <table><thead><tr><th>Posición</th><th>{data.participation_mode==='individual'?'Participante':'Equipo'}</th><th>Puntos</th></tr></thead><tbody>{data.leaderboard.map((row,i)=><tr key={i} className={row.rank<=3?'podium-row':''}><td><span>{String(row.rank).padStart(2,'0')}</span></td><td>{row.name}</td><td>{row.score}</td></tr>)}</tbody></table>;
}
export default function LeaderboardScreen({share}:{share:string}) {
 const [data,setData]=useState<ScreenData|null>(null);
 const [error,setError]=useState('');
 const [connected,setConnected]=useState(false);
 useEffect(()=>{
  let cancelled=false;let timer:number;const controller=new AbortController();
  async function refresh(){
   try {
    const next=await request<ScreenData>('/api/v1/screens/'+encodeURIComponent(share),undefined,{signal:controller.signal});
    if(cancelled)return;setData(next);setConnected(true);setError('');
   }catch(e){if(cancelled)return;setConnected(false);if(e instanceof ApiError&&e.status===404)setData(null);setError(e instanceof ApiError&&e.status===404?'Este enlace no está disponible. Pide al instructor un enlace nuevo.':'Sin conexión. Intentando actualizar…');}
   if(!cancelled)timer=window.setTimeout(refresh,3000);
  }
  void refresh();return()=>{cancelled=true;controller.abort();window.clearTimeout(timer);};
 },[share]);
 return <main className="arena-screen"><header><a href="/" className="screen-brand">CloudOps <b>Arena</b></a><button className="secondary-button" onClick={()=>{void document.documentElement.requestFullscreen?.().catch(()=>setError('Usa la opción de pantalla completa del navegador.'));}}><Maximize size={17}/> Pantalla completa</button></header>
 <section className="screen-title"><div><p>CLASIFICACIÓN</p><h1>{data?.title||'Marcador de la Arena'}</h1><span>{data?.mission}</span></div><Trophy size={52}/></section>
 <div className="screen-status" role="status"><span className={connected?'connected':''}/>{connected?'Actualización automática · cada 3 s':'Conectando…'}{data&&<><b>{data.status==='finished'?'Resultado final':data.status==='paused'?'Partida pausada':'Partida abierta'}</b><time>Última actualización: {new Date(data.updated_at).toLocaleTimeString()}</time></>}</div>
 <p className="muted-note">A igual puntaje, primero quien lo alcanzó antes con sus respuestas aprobadas.</p>
 {error&&<p className="screen-error" role="alert">{error}{data&&' Se conserva la última clasificación recibida.'}</p>}
 {data&&(data.leaderboard.length?<ScreenTable data={data}/>:<p className="screen-empty">Esperando a los primeros participantes.</p>)}
 <footer>CloudOps Arena · Puntos por evidencias verificadas</footer></main>;
}
