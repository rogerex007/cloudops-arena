import {useEffect,useState,useRef} from 'react';
import {Clock3} from 'lucide-react';
export type MissionClock={server_now:number;remaining_seconds:number|null;deadline:number|null;paused:boolean;closed:boolean};
export function formatTime(seconds:number) {
  return `${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`;
}
export default function MissionTimer({clock,onClosed}:{clock?:MissionClock;onClosed?:()=>void}) {
  const [now,setNow]=useState(Date.now());
  const anchor=useRef({tag:'',at:Date.now()});
  const tag=`${clock?.server_now}:${clock?.deadline}:${clock?.paused}`;
  if(anchor.current.tag!==tag)anchor.current={tag,at:Date.now()};
  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),1000);
    return ()=>window.clearInterval(timer);
  },[]);
  const elapsed=Math.max(0,Math.floor((now-anchor.current.at)/1000));
  const remaining=clock?.remaining_seconds==null?null:Math.max(0,clock.remaining_seconds-(clock.paused?0:elapsed));
  const closed=clock?.closed||remaining===0;
  useEffect(()=>{if(closed)onClosed?.();},[closed,onClosed]);
  return <div className={`mission-timer ${closed?'is-closed':remaining!==null&&remaining<60?'is-urgent':''}`} role="timer" aria-label="Tiempo restante de la misión">
    <Clock3 size={20}/><div><span>{closed?'MISIÓN CERRADA':clock?.paused?'RELOJ EN PAUSA':remaining===null?'SIN RELOJ ACTIVO':'TIEMPO DE LA MISIÓN'}</span><b>{remaining===null?'—':formatTime(remaining)}</b></div>
    <small>{closed?'No se aceptan nuevas entregas':remaining===null?'El instructor lo inicia al activar':'Las entregas en cola pueden terminar'}</small>
  </div>;
}
