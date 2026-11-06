import {useEffect, useState} from 'react';
import {Cloud,RefreshCw} from 'lucide-react';
import {request} from './api';

type Snapshot={functions:string[];tables:string[];queues:string[];buses:string[];order_count:number;processed_count:number};
type Deployment={status:string;message:string;snapshot?:Snapshot|null;captured_at?:number;repo_name?:string;deployment?:{commit_sha:string;evaluation_id:string}};
export default function Playground({token,eventStatus}:{token:string;eventStatus:string}) {
  const [deployment,setDeployment]=useState<Deployment|null>(null);
  const [error,setError]=useState('');
  const [refreshKey,setRefreshKey]=useState(0);
  const [tab,setTab]=useState<keyof Pick<Snapshot,'functions'|'tables'|'queues'|'buses'>>('functions');
  useEffect(()=>{
    let disposed=false,loading=false;
    async function refresh() {
      if(loading||document.hidden)return;
      loading=true;
      try {
        const result=await request<Deployment>('/api/v1/participant/playground',token);
        if(!disposed){setDeployment(result);setError('');}
      } catch(e) {if(!disposed){setDeployment(null);setError((e as Error).message);}}
      finally{loading=false;}
    }
    void refresh();
    const timer=window.setInterval(()=>void refresh(),10000+Math.random()*3000);
    return ()=>{disposed=true;window.clearInterval(timer);};
  },[token,eventStatus,refreshKey]);
  const snapshot=deployment?.deployment ? deployment.snapshot : null;
  const titles={functions:'Lambda',tables:'DynamoDB',queues:'SQS',buses:'EventBridge'};
  return <section className="playground-console side-card" aria-label="Mi playground">
    <div className="section-heading"><div><div className="eyebrow">INFRAESTRUCTURA DEL LABORATORIO</div><h2><Cloud size={22}/> Mi playground</h2></div><button className="secondary-button" onClick={()=>setRefreshKey(value=>value+1)}><RefreshCw size={16}/> Actualizar vista</button></div>
    <div className="playground-status" role="status"><b>{snapshot?'Desplegado · conservado en disco':deployment?.status==='expired'?'Laboratorio finalizado':'Sin despliegue del participante'}</b></div>
    <p>{deployment?.message||'No se muestran recursos sin un despliegue asociado a tu entrega.'}</p>
    {snapshot&&<>
      <p>Repositorio: <b>{deployment?.repo_name}</b> · Commit: <code>{deployment?.deployment?.commit_sha}</code></p>
      <p className="muted-note"><b>Última captura:</b> {new Date((deployment?.captured_at||0)*1000).toLocaleString()}. La VM se conserva apagada entre operaciones; esta vista no es en vivo.</p>
      <div className="playground-tabs">{(Object.keys(titles) as (keyof typeof titles)[]).map(key=><button key={key} className={`small-button ${tab===key?'selected':''}`} onClick={()=>setTab(key)}>{titles[key]} · {snapshot[key].length}</button>)}</div>
      <div className="playground-resources">{snapshot[tab].map(name=><div key={name}><Cloud size={15}/><code>{name}</code><span>Desplegado</span></div>)}</div>
    </>}
    {error&&<p className="playground-error" role="alert">{error}</p>}
    <p className="muted-note">La infraestructura aparece tras un despliegue verificado desde Actions. Aprobar un plan o preparar una plantilla de referencia no equivale a desplegar tu entrega. Actualizar esta vista no crea recursos.</p>
  </section>;
}
