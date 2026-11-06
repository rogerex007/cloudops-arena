const API = import.meta.env.VITE_API_BASE_URL || '';

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message); this.name = 'ApiError'; this.status = status;
  }
}

export type Participant = {
  id: string;
  name: string;
  team_id: string;
  team_name: string;
  is_team_leader?: boolean;
  participation_mode?: 'individual' | 'team';
};
export type Mission = {
  id: string; title: string; type: string; category: string; points: number;
  duration_minutes: number; description: string; instructions: string[];
  resources?: { name: string; purpose: string }[];
  repository_link_points?: number;
  completed?: boolean; active?: boolean; locked?: boolean;
  quiz?: { question: string; options: string[] };
  workflow?: string;
  materials?: { title: string; filename: string; instructions: string[] };
};
export type Evaluation = {
  operation?: 'plan' | 'deploy';
  evaluation_id: string; mission_id: string; repo_name: string;
  commit_sha: string; status: 'pending' | 'preparing' | 'running' | 'passed' | 'failed' | 'blocked'; created_at: string;
  message?: string; result_code?: string; missing_files?: string[];
  updated_at?: string; attempt?: number;
  queue_position?: number; queue_total?: number;
  points_awarded?: number;
  source?: string; actions_url?: string;
  progress?: {stage: string; status: 'running' | 'passed' | 'failed'; message: string; timestamp: string}[];
};
export type PublicEvent = {
  event_id: string;
  event_code: string;
  title: string;
  status: string;
  participation_mode: 'individual' | 'team';
  team_size: number;
  max_participants: number;
  game_pack: string;
};
export type ParticipantAuthResult = {
  access_token: string;
  token_type: string;
  participant: Participant;
  invite_code?: string;
  invite_url?: string;
};

export async function request<T>(path: string, token?: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${API}${path}`, { ...init, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((item: { msg?: string }) => item.msg || 'Dato inválido').join('. ')
        : `No fue posible completar la solicitud (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export async function downloadMaterials(missionId: string, token: string): Promise<Blob> {
  const response = await fetch(`${API}/api/v1/participant/missions/${encodeURIComponent(missionId)}/materials`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'No fue posible descargar el kit. Intenta nuevamente.');
  }
  if (!response.headers.get('Content-Type')?.includes('application/zip')) {
    throw new Error('No recibimos el kit. Actualiza el portal y verifica que tu sesión de acceso siga activa.');
  }
  return response.blob();
}

export async function watchEvaluation(id: string, token: string, signal: AbortSignal, update: (value: Evaluation) => void) {
  const response = await fetch(`${API}/api/v1/participant/evaluations/${encodeURIComponent(id)}/events`, {
    headers: {Authorization: `Bearer ${token}`}, signal,
  });
  if (!response.ok || !response.headers.get('Content-Type')?.includes('text/event-stream') || !response.body) {
    throw new Error('La conexión en vivo no está disponible.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let end;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
        const data = frame.split('\n').find(line => line.startsWith('data: '));
        if (data) update(JSON.parse(data.slice(6)) as Evaluation);
      }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
