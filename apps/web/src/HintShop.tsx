import {useState} from 'react';
import {Coins,Lightbulb,LockKeyhole} from 'lucide-react';
import {request} from './api';
export type Hint={id:string;title:string;cost:number;purchased:boolean;content?:string};
export default function HintShop({token,mission,hints,balance,closed,onChanged}:{token:string;mission:string;hints:Hint[];balance:number;closed:boolean;onChanged:()=>Promise<void>}) {
  const [unlocked,setUnlocked]=useState<Record<string,Hint>>({});
  const [busy,setBusy]=useState('');const [error,setError]=useState('');
  async function buy(hint:Hint) {
    setBusy(hint.id);setError('');
    try {
      const result=await request<{hint:Hint}>(`/api/v1/participant/missions/${encodeURIComponent(mission)}/hints/${encodeURIComponent(hint.id)}`,token,{method:'POST'});
      setUnlocked(value=>({...value,[hint.id]:result.hint}));await onChanged();
    } catch(e){setError((e as Error).message);}finally{setBusy('');}
  }
  if(!hints.length)return null;
  return <section className="hint-shop">
    <p>Una compra por pista. El costo se descuenta de tus monedas y la pista queda disponible para tu equipo.</p>
    <div className="hint-grid">{hints.map(original=>{
      const hint=unlocked[original.id]||original;
      return <article className={`hint-card ${hint.purchased?'unlocked':''}`} key={hint.id}>
        <div className="hint-title">{hint.purchased?<Lightbulb size={18}/>:<LockKeyhole size={18}/>}<b>{hint.title}</b><span>{hint.cost} <Coins size={13}/></span></div>
        {hint.purchased?<p className="hint-content">{hint.content}</p>:<><p>Una orientación para resolver el siguiente paso por tu cuenta.</p><button className="secondary-button" disabled={!!busy||closed||balance<hint.cost} onClick={()=>void buy(hint)}>{busy===hint.id?'Comprando…':closed?'Misión cerrada':balance<hint.cost?'Necesitas más monedas':`Comprar por ${hint.cost} monedas`}</button></>}
      </article>;
    })}</div>{error&&<p role="alert" className="playground-error">{error}</p>}
  </section>;
}
