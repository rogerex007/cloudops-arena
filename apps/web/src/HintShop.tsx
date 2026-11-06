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
    <div className="section-heading"><div><div className="eyebrow">UNA AYUDA, NO LA RESPUESTA</div><h3><Lightbulb size={20}/> Centro de pistas</h3></div><span className="coin-badge"><Coins size={17}/>{balance} monedas</span></div>
    <p>Gana 10 monedas al completar cada misión. Comprar pistas no reduce tus puntos. En equipo, el saldo y las pistas se comparten.</p>
    <div className="hint-grid">{hints.map(original=>{
      const hint=unlocked[original.id]||original;
      return <article className={`hint-card ${hint.purchased?'unlocked':''}`} key={hint.id}>
        <div className="hint-title">{hint.purchased?<Lightbulb size={18}/>:<LockKeyhole size={18}/>}<b>{hint.title}</b><span>{hint.cost} <Coins size={13}/></span></div>
        {hint.purchased?<p className="hint-content">{hint.content}</p>:<><p>Una orientación para resolver el siguiente paso por tu cuenta.</p><button className="secondary-button" disabled={!!busy||closed||balance<hint.cost} onClick={()=>void buy(hint)}>{busy===hint.id?'Comprando…':closed?'Misión cerrada':balance<hint.cost?'Necesitas más monedas':`Comprar por ${hint.cost} monedas`}</button></>}
      </article>;
    })}</div>{error&&<p role="alert" className="playground-error">{error}</p>}
  </section>;
}
