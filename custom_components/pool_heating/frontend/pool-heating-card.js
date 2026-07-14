/* Pool Heating Card — bundled with the pool_heating integration.
 *
 * Zero external dependencies (no Mushroom / apexcharts / mini-graph-card).
 * The integration serves and registers this file automatically; just add:
 *
 *   type: custom:pool-heating-card
 *   entity: sensor.<name>_status
 *
 * Everything else (mode select, prediction, power, energy) is derived from
 * the status entity's siblings; each id can be overridden in the config.
 */
(() => {
  "use strict";

  const STATUS_COLORS = {
    heating: "#e03131",
    frost_protect: "#e03131",
    target_reached: "#2f9e44",
    idle_band: "#2f9e44",
    waiting_rain: "#1971c2",
    waiting_cold: "#1971c2",
    waiting_cold_now: "#1971c2",
    waiting_better_window: "#1971c2",
    no_window: "#1971c2",
    waiting_price: "#f08c00",
    night_off: "#868e96",
    mode_off: "#868e96",
    waiting_filtration: "#868e96",
    compressor_protect: "#868e96",
    manual_override: "#9c36b5",
    sensor_unavailable: "#e03131",
    switch_unavailable: "#e03131",
    forecast_unavailable: "#f08c00",
  };

  const ICONS = {
    heating: "M12 3l4 4h-3v6h-2V7H8l4-4M5 20v-2h14v2H5m0-4v-2h14v2H5z",
    default:
      "M2 12c1.1 0 1.6-.6 2.6-.6s1.5.6 2.6.6 1.6-.6 2.6-.6 1.5.6 2.6.6 1.6-.6 2.6-.6 1.5.6 2.6.6 1.6-.6 2.6-.6V14c-1.1 0-1.6.6-2.6.6s-1.5-.6-2.6-.6-1.6.6-2.6.6-1.5-.6-2.6-.6-1.6.6-2.6.6-1.5-.6-2.6-.6V12m0 5c1.1 0 1.6-.6 2.6-.6s1.5.6 2.6.6 1.6-.6 2.6-.6 1.5.6 2.6.6 1.6-.6 2.6-.6 1.5.6 2.6.6 1.6-.6 2.6-.6V19c-1.1 0-1.6.6-2.6.6s-1.5-.6-2.6-.6-1.6.6-2.6.6-1.5-.6-2.6-.6-1.6.6-2.6.6-1.5-.6-2.6-.6V17M8.7 4.2A3.7 3.7 0 0 1 12.4 8a3.7 3.7 0 0 1-.4 1.7c1 .1 1.5.6 2.5.6.3 0 .6-.1.8-.2A5.7 5.7 0 0 0 8.7 2.2 5.7 5.7 0 0 0 3 7.9v.2c.6-.2 1-.4 1.9-.5a3.7 3.7 0 0 1 3.8-3.4z",
  };

  const MODES = ["auto", "off", "force_on"];
  const MODE_LABELS = { auto: "Auto", off: "Off", force_on: "Force" };

  const num = (v) => {
    const f = parseFloat(v);
    return Number.isFinite(f) ? f : null;
  };

  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[ch]);

  class PoolHeatingCard extends HTMLElement {
    static getStubConfig(hass) {
      const entity = Object.keys(hass?.states || {}).find(
        (id) =>
          id.startsWith("sensor.") &&
          id.endsWith("_status") &&
          hass.states[id].attributes?.reason !== undefined &&
          hass.states[id].attributes?.forecast_available !== undefined
      );
      return { entity: entity || "sensor.pool_heating_status" };
    }

    setConfig(config) {
      if (!config || !config.entity) {
        throw new Error("pool-heating-card: set `entity` to the status sensor");
      }
      this._config = config;
      this._built = false;
      this._history = null;
      this._historyAt = 0;
      this._historyFor = null;
    }

    set hass(hass) {
      this._hass = hass;
      if (!this._config) return;
      if (!this._built) this._build();
      this._render();
    }

    getCardSize() {
      return this._config?.hide_graph ? 4 : 7;
    }

    _ids() {
      const cfg = this._config;
      const base = cfg.entity.replace(/^sensor\./, "").replace(/_status$/, "");
      return {
        status: cfg.entity,
        predicted: cfg.predicted_ready_entity || `sensor.${base}_predicted_ready`,
        mode: cfg.mode_entity || `select.${base}_mode`,
        power: cfg.power_entity || `sensor.${base}_power`,
        energy: cfg.energy_entity || `sensor.${base}_energy_consumed`,
      };
    }

    _build() {
      this._built = true;
      const card = document.createElement("ha-card");
      card.innerHTML = `
        <style>
          .phc { padding: 12px 16px 16px; }
          .phc-head { display: flex; align-items: center; gap: 12px; }
          .phc-icon {
            flex: none; width: 42px; height: 42px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
          }
          .phc-icon svg { width: 24px; height: 24px; }
          .phc-titles { min-width: 0; }
          .phc-name { font-weight: 600; font-size: 15px; }
          .phc-state { font-size: 13px; color: var(--secondary-text-color); }
          .phc-reason {
            margin: 10px 0 0; font-size: 13px; line-height: 1.35;
            color: var(--primary-text-color);
          }
          .phc-chips {
            display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px;
          }
          .phc-chip {
            font-size: 12px; padding: 3px 10px; border-radius: 12px;
            background: var(--secondary-background-color, rgba(120,120,120,.12));
            color: var(--primary-text-color); white-space: nowrap;
          }
          .phc-modes { display: flex; gap: 6px; margin-top: 12px; }
          .phc-mode {
            flex: 1; text-align: center; font-size: 12px; padding: 6px 0;
            border-radius: 8px; cursor: pointer; user-select: none;
            border: 1px solid var(--divider-color, rgba(120,120,120,.3));
            color: var(--primary-text-color); background: transparent;
          }
          .phc-mode.on {
            background: var(--primary-color); color: var(--text-primary-color, #fff);
            border-color: var(--primary-color);
          }
          .phc-graph { margin-top: 12px; }
          .phc-graph svg { width: 100%; height: auto; display: block; }
          .phc-legend {
            display: flex; gap: 12px; margin-top: 4px; font-size: 11px;
            color: var(--secondary-text-color);
          }
          .phc-dot {
            display: inline-block; width: 8px; height: 8px; border-radius: 50%;
            margin-right: 4px;
          }
          .phc-err { color: var(--error-color, #e03131); font-size: 13px; padding: 8px 0; }
        </style>
        <div class="phc">
          <div class="phc-head">
            <div class="phc-icon"><svg viewBox="0 0 24 24"><path fill="currentColor"/></svg></div>
            <div class="phc-titles">
              <div class="phc-name"></div>
              <div class="phc-state"></div>
            </div>
          </div>
          <p class="phc-reason"></p>
          <div class="phc-chips"></div>
          <div class="phc-modes"></div>
          <div class="phc-graph"></div>
          <div class="phc-legend"></div>
        </div>`;
      this._el = {
        card,
        icon: card.querySelector(".phc-icon"),
        iconPath: card.querySelector(".phc-icon path"),
        name: card.querySelector(".phc-name"),
        state: card.querySelector(".phc-state"),
        reason: card.querySelector(".phc-reason"),
        chips: card.querySelector(".phc-chips"),
        modes: card.querySelector(".phc-modes"),
        graph: card.querySelector(".phc-graph"),
        legend: card.querySelector(".phc-legend"),
      };
      this.replaceChildren(card);
    }

    _render() {
      const hass = this._hass;
      const ids = this._ids();
      const st = hass.states[ids.status];
      const el = this._el;
      if (!st) {
        el.reason.innerHTML = `<span class="phc-err">Entity ${esc(ids.status)} not found</span>`;
        return;
      }
      const a = st.attributes;
      const color = STATUS_COLORS[st.state] || "#868e96";

      el.icon.style.background = `${color}22`;
      el.icon.style.color = color;
      el.iconPath.setAttribute(
        "d", st.state === "heating" || st.state === "frost_protect"
          ? ICONS.heating : ICONS.default
      );
      el.name.textContent =
        this._config.name || a.friendly_name?.replace(/ Status$/i, "") || "Pool heating";
      el.state.textContent = hass.formatEntityState
        ? hass.formatEntityState(st) : st.state;
      el.state.style.color = color;
      el.reason.textContent = a.reason || "";

      this._renderChips(a, ids);
      this._renderModes(a.mode);
      if (!this._config.hide_graph) this._renderGraph(a, ids);
    }

    _chip(label, value) {
      return value == null || value === ""
        ? "" : `<span class="phc-chip">${esc(label)} ${esc(value)}</span>`;
    }

    _fmtTime(iso) {
      if (!iso) return null;
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return null;
      const lang = this._hass?.locale?.language || "en";
      return d.toLocaleString(lang, {
        weekday: "short", hour: "2-digit", minute: "2-digit",
      });
    }

    _renderChips(a, ids) {
      const hass = this._hass;
      const power = num(hass.states[ids.power]?.state);
      const energy = num(hass.states[ids.energy]?.state);
      const chips = [
        this._chip("💧", a.pool_temp != null ? `${a.pool_temp} / ${a.target_temp} °C` : null),
        this._chip("🌡", a.outdoor_temp != null ? `${a.outdoor_temp} °C` : null),
        this._chip("✅", this._fmtTime(a.predicted_ready)),
        this._chip("⚡", power != null ? `${Math.round(power)} W` : null),
        this._chip("🔋", energy != null ? `${energy.toFixed(1)} kWh` : null),
        this._chip("💶", a.estimated_cost_eur != null ? `~${a.estimated_cost_eur} €` : null),
        this._chip("🧠", a.model_confidence != null ? `${a.model_confidence} %` : null),
      ];
      this._el.chips.innerHTML = chips.join("");
    }

    _renderModes(current) {
      const ids = this._ids();
      this._el.modes.innerHTML = MODES.map(
        (m) =>
          `<button class="phc-mode${m === current ? " on" : ""}" data-mode="${m}">
             ${MODE_LABELS[m]}</button>`
      ).join("");
      this._el.modes.querySelectorAll(".phc-mode").forEach((btn) => {
        btn.onclick = () =>
          this._hass.callService("select", "select_option", {
            entity_id: ids.mode,
            option: btn.dataset.mode,
          });
      });
    }

    async _maybeFetchHistory(poolEntity) {
      const now = Date.now();
      if (
        this._history &&
        this._historyFor === poolEntity &&
        now - this._historyAt < 5 * 60 * 1000
      ) {
        return;
      }
      this._historyAt = now;
      this._historyFor = poolEntity;
      try {
        const start = new Date(now - 24 * 3600 * 1000).toISOString();
        const res = await this._hass.callApi(
          "GET",
          `history/period/${start}?filter_entity_id=${poolEntity}` +
            `&minimal_response&no_attributes&significant_changes_only=0`
        );
        const series = (res?.[0] || [])
          .map((s) => [new Date(s.last_changed || s.lu * 1000).getTime(), num(s.state)])
          .filter((p) => p[1] != null && !Number.isNaN(p[0]));
        this._history = series;
        this._render();
      } catch (e) {
        this._history = [];
      }
    }

    _renderGraph(a, ids) {
      const el = this._el;
      const pred = this._hass.states[ids.predicted];
      const pa = pred?.attributes || {};
      const target = num(pa.target_temp ?? a.target_temp);
      const poolEntity = pa.pool_entity;
      if (poolEntity) this._maybeFetchHistory(poolEntity);

      const nowMs = Date.now();
      const hist = (this._history || []).filter((p) => p[0] <= nowMs);
      if (a.pool_temp != null) hist.push([nowMs, a.pool_temp]);
      const fc = (pa.forecast || [])
        .map((p) => [new Date(p.datetime).getTime(), num(p.temperature)])
        .filter((p) => p[1] != null && p[0] >= nowMs - 3600e3)
        .slice(0, 72);

      if (!hist.length && !fc.length) {
        el.graph.innerHTML = "";
        el.legend.innerHTML = "";
        return;
      }

      const W = 480, H = 140, PL = 30, PR = 6, PT = 8, PB = 18;
      const all = hist.concat(fc);
      const xs = all.map((p) => p[0]);
      const ysArr = all.map((p) => p[1]).concat(target != null ? [target] : []);
      const xMin = Math.min(...xs), xMax = Math.max(...xs);
      let yMin = Math.min(...ysArr), yMax = Math.max(...ysArr);
      if (yMax - yMin < 2) { yMin -= 1; yMax += 1; }
      const pad = (yMax - yMin) * 0.1;
      yMin -= pad; yMax += pad;

      const X = (t) => PL + ((t - xMin) / Math.max(1, xMax - xMin)) * (W - PL - PR);
      const Y = (v) => PT + (1 - (v - yMin) / (yMax - yMin)) * (H - PT - PB);
      const path = (pts) =>
        pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");

      const lang = this._hass?.locale?.language || "en";
      const fmtTick = (t) =>
        new Date(t).toLocaleString(lang, { weekday: "short", hour: "2-digit" });

      let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">`;
      // horizontal gridlines + labels
      for (const v of [yMin + pad, (yMin + yMax) / 2, yMax - pad]) {
        svg += `<line x1="${PL}" y1="${Y(v)}" x2="${W - PR}" y2="${Y(v)}"
                  stroke="var(--divider-color, #8884)" stroke-width="0.5"/>
                <text x="2" y="${Y(v) + 3}" font-size="9"
                  fill="var(--secondary-text-color, #888)">${v.toFixed(1)}</text>`;
      }
      // target line
      if (target != null && target >= yMin && target <= yMax) {
        svg += `<line x1="${PL}" y1="${Y(target)}" x2="${W - PR}" y2="${Y(target)}"
                  stroke="#0ca678" stroke-width="1" stroke-dasharray="5,4"/>`;
      }
      // now marker
      if (nowMs >= xMin && nowMs <= xMax) {
        svg += `<line x1="${X(nowMs)}" y1="${PT}" x2="${X(nowMs)}" y2="${H - PB}"
                  stroke="var(--secondary-text-color, #888)" stroke-width="0.7"
                  stroke-dasharray="2,3"/>`;
      }
      if (hist.length > 1) {
        svg += `<path d="${path(hist)}" fill="none" stroke="#2f9e44" stroke-width="2"/>`;
      }
      if (fc.length > 1) {
        svg += `<path d="${path(fc)}" fill="none" stroke="#f08c00" stroke-width="2"
                  stroke-dasharray="6,4"/>`;
      }
      // x-axis ticks: start / now / end
      for (const t of [xMin, nowMs, xMax]) {
        if (t < xMin || t > xMax) continue;
        const anchor = t === xMin ? "start" : t === xMax ? "end" : "middle";
        svg += `<text x="${X(t)}" y="${H - 5}" font-size="9" text-anchor="${anchor}"
                  fill="var(--secondary-text-color, #888)">${esc(fmtTick(t))}</text>`;
      }
      svg += "</svg>";
      el.graph.innerHTML = svg;
      el.legend.innerHTML = `
        <span><span class="phc-dot" style="background:#2f9e44"></span>história</span>
        <span><span class="phc-dot" style="background:#f08c00"></span>predikcia</span>
        ${target != null ? '<span><span class="phc-dot" style="background:#0ca678"></span>cieľ</span>' : ""}`;
    }
  }

  if (!customElements.get("pool-heating-card")) {
    customElements.define("pool-heating-card", PoolHeatingCard);
  }
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === "pool-heating-card")) {
    window.customCards.push({
      type: "pool-heating-card",
      name: "Pool Heating Card",
      description:
        "Status, reason, mode and temperature prediction for the Pool Heating Controller (no dependencies).",
      preview: true,
    });
  }
})();
