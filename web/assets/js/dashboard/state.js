export function createDashboardState() {
  return {token: "", connected: false, page: 0, pages: 0, busy: false, timer: null, catalogs: {}, filters: new URLSearchParams(), generation: 0};
}
