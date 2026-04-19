/* ── NutriLogBot WebApp API client ──────────────────────────────────────────
 *
 * Thin typed wrappers around fetch() for the /api/* endpoints.
 * Handles Telegram auth header (`Authorization: tma <initData>`) and JSON.
 *
 * Exposed globally as `window.API`.
 *
 * All methods:
 *   - throw on non-2xx responses (Error.message = "STATUS body")
 *   - return parsed JSON (or null for 204 No Content)
 */
(function () {
  'use strict';

  function authHeader() {
    const initData = window.Telegram?.WebApp?.initData || '';
    return { 'Authorization': `tma ${initData}` };
  }

  async function request(path, options = {}) {
    const headers = {
      ...authHeader(),
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };
    const r = await fetch(path, { ...options, headers });
    if (!r.ok) {
      const body = await r.text();
      throw new Error(`${r.status} ${body}`);
    }
    return r.status === 204 ? null : r.json();
  }

  window.API = {
    // GET /api/day?date=YYYY-MM-DD
    getDay(dateISO) {
      return request(`/api/day?date=${encodeURIComponent(dateISO)}`);
    },

    // POST /api/meal/item  {date, slot, name, weight, source?}
    addItem({ date, slot, name, weight, source = 'manual' }) {
      return request('/api/meal/item', {
        method: 'POST',
        body: JSON.stringify({ date, slot, name, weight, source }),
      });
    },

    // PATCH /api/meal/item  {meal_id, idx, weight}
    patchWeight({ meal_id, idx, weight }) {
      return request('/api/meal/item', {
        method: 'PATCH',
        body: JSON.stringify({ meal_id, idx, weight }),
      });
    },

    // DELETE /api/meal/item?meal_id=&idx=
    deleteItem({ meal_id, idx }) {
      return request(
        `/api/meal/item?meal_id=${meal_id}&idx=${idx}`,
        { method: 'DELETE' }
      );
    },

    // GET /api/favorites?limit=N
    getFavorites(limit = 15) {
      return request(`/api/favorites?limit=${limit}`);
    },

    // Escape hatch for ad-hoc calls (e.g. /api/settings).
    request,
  };
})();
