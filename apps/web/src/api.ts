const API = import.meta.env.VITE_API_BASE_URL || '';

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
    throw new Error(message);
  }
  return body as T;
}
