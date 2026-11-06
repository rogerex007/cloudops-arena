// Routing selects a UI/session only. The API still authorizes every request.
type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const INSTRUCTOR_TOKEN = 'arena-instructor-token';

export function isInstructorPath(path: string): boolean {
  return path === '/instructor' || path.startsWith('/instructor/');
}

export function loadSession(instructor: boolean, local: Store, tab: Store) {
  if (instructor) {
    let token = tab.getItem(INSTRUCTOR_TOKEN) || '';
    // Migrate the previous shared administrator session only on its own route.
    if (local.getItem('arena-role') === 'admin') {
      token ||= local.getItem('arena-token') || '';
      if (token) tab.setItem(INSTRUCTOR_TOKEN, token);
      local.removeItem('arena-token');
      local.removeItem('arena-role');
    }
    return {token, role: token ? 'admin' : ''};
  }
  const token = local.getItem('arena-role') === 'participant' ? local.getItem('arena-token') || '' : '';
  return {token, role: token ? 'participant' : ''};
}

export function saveSession(instructor: boolean, token: string, role: string, local: Store, tab: Store) {
  if (role !== (instructor ? 'admin' : 'participant')) throw new Error('La sesión no corresponde a este portal.');
  if (instructor) tab.setItem(INSTRUCTOR_TOKEN, token);
  else {
    local.setItem('arena-token', token);
    local.setItem('arena-role', role);
  }
}

export function clearSession(instructor: boolean, local: Store, tab: Store) {
  if (instructor) tab.removeItem(INSTRUCTOR_TOKEN);
  else {
    local.removeItem('arena-token');
    local.removeItem('arena-role');
    local.removeItem('arena-participant');
    tab.removeItem('arena-team-invite');
  }
}
