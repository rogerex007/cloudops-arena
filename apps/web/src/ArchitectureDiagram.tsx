import {useId,useState} from 'react';
export type Architecture={title:string;subtitle:string;pipeline:string[];nodes:{id:string;label:string;service:string;kind:string;x:number;y:number;detail:string}[];edges:{from:string;to:string;label?:string;dashed?:boolean}[];note:string};
export default function ArchitectureDiagram({architecture:a}:{architecture:Architecture}){
 const [selected,setSelected]=useState<string|null>(null);const marker=useId().replace(/:/g,'');
 const current=a.nodes.find(node=>node.id===selected);
 return <section className="architecture-panel"><header><div className="eyebrow">ARQUITECTURA DEL LABORATORIO</div><h2>{a.title}</h2><p>{a.subtitle}</p></header>
 <div className="architecture-pipeline" aria-label="Flujo de despliegue">{a.pipeline.map((step,i)=><span key={step}>{i>0&&<b aria-hidden="true">→</b>}{step}</span>)}</div>
 <p className="architecture-guide">Selecciona un recurso para ver su función. En móvil puedes desplazar el diagrama horizontalmente.</p>
 <div className="architecture-scroll" tabIndex={0} aria-label="Diagrama de arquitectura desplazable"><svg viewBox="0 0 1100 590" role="img" aria-labelledby={marker+'title'}>
 <title id={marker+'title'}>{a.title}. {a.subtitle}</title><defs><marker id={marker} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 Z" fill="#71b8ef"/></marker></defs>
 <rect className="architecture-boundary" x="170" y="22" width="916" height="550" rx="18"/><text className="boundary-label" x="192" y="49">LABORATORIO AISLADO · FLOCI</text>
 {a.edges.map((edge,i)=>{const from=a.nodes.find(n=>n.id===edge.from),to=a.nodes.find(n=>n.id===edge.to);if(!from||!to)return null;const vertical=from.x===to.x;const x1=from.x+(vertical?75:150),y1=from.y+(vertical?82:41),x2=to.x+(vertical?75:0),y2=to.y+(vertical?0:41);const mid=(x1+x2)/2;return <g key={i} className={edge.dashed?'edge dashed':'edge'}><path d={vertical?`M${x1} ${y1} V${y2}`:`M${x1} ${y1} H${mid} V${y2} H${x2}`} markerEnd={`url(#${marker})`}/>{edge.label&&<text x={vertical?x1+9:mid} y={vertical?(y1+y2)/2:y2-12} textAnchor={vertical?'start':'middle'}>{edge.label}</text>}</g>;})}
 {a.nodes.map(node=><g key={node.id} className={`architecture-node ${node.kind} ${selected===node.id?'selected':''}`} transform={`translate(${node.x},${node.y})`} role="button" tabIndex={0} aria-label={`${node.service}: ${node.label}`} aria-pressed={selected===node.id} onClick={()=>setSelected(node.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(node.id);}}}><rect width="150" height="82" rx="12"/><rect className="node-icon-bg" x="11" y="12" width="30" height="30" rx="7"/><text className="node-symbol" x="26" y="34" textAnchor="middle">{({compute:'λ',queue:'≋',database:'▤',event:'◇',client:'◎'} as Record<string,string>)[node.kind]||'◇'}</text><text className="node-service" x="50" y="31">{node.service}</text><text className="node-label" x="12" y="65">{node.label}</text></g>)}
 </svg></div>
 <div className="architecture-inspector" aria-live="polite"><b>{current?`${current.service} · ${current.label}`:'El recorrido de un pedido'}</b><p>{current?.detail||a.note}</p></div>
 <p className="architecture-caption">Este esquema explica el ejercicio. Consulta Infraestructura para ver los recursos verificados de tu entrega. Las misiones 03/04 se evalúan con recursos temporales.</p></section>;
}
