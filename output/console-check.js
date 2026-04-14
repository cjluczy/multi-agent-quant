
    const ROUTES = {
      overview: { label: "总览", brief: "账户与风险", eyebrow: "Workspace / Overview", title: "总览", subtitle: "账户状态" },
      run: { label: "运行", brief: "参数与启动", eyebrow: "Workspace / Run", title: "运行", subtitle: "参数配置" },
      agents: { label: "智能体", brief: "贡献与曲线", eyebrow: "Workspace / Agents", title: "智能体", subtitle: "表现归因" },
      portfolio: { label: "持仓", brief: "仓位与流水", eyebrow: "Workspace / Portfolio", title: "持仓", subtitle: "组合账本" },
      history: { label: "历史", brief: "历史与对比", eyebrow: "Workspace / History", title: "历史", subtitle: "回顾与实验" }
    };
    const AVAILABLE_AGENT_ROLES = [
      ["news_event", "新闻事件"],
      ["reactive", "反应式交易"],
      ["swing", "波段交易"],
      ["futures_hedge", "期货对冲"],
      ["mean_reversion", "均值回归"],
      ["breakout", "突破交易"],
      ["fundamental", "基本面精选"]
    ];

    const nav = document.getElementById("nav");
    const sidebarPanel = document.getElementById("sidebarPanel");
    const routeEyebrow = document.getElementById("routeEyebrow");
    const routeTitle = document.getElementById("routeTitle");
    const routeSubtitle = document.getElementById("routeSubtitle");
    const statusBadge = document.getElementById("statusBadge");
    const statusLine = document.getElementById("statusLine");
    const notice = document.getElementById("notice");
    const view = document.getElementById("view");
    const runButton = document.getElementById("runButton");

    const POLL_MS = 1500;
    let currentState = null;
    let configDraft = null;
    let draftDirty = false;
    let fetchInFlight = false;
    let poller = null;
    let lastRoute = null;
    let lastNavHtml = "";
    let lastSidebarHtml = "";
    let lastNoticeHtml = "";
    let lastNoticeTone = "";
    let lastViewHtml = "";
    let lastSyncAt = null;

    function routePath(route) {
      return `/console/${route}`;
    }

    function getRoute() {
      const path = window.location.pathname.replace(/\/+$/, "");
      const last = path.split("/").filter(Boolean).pop() || "";
      return ROUTES[last] ? last : "overview";
    }

    function ensureRoute() {
      const route = getRoute();
      const expected = routePath(route);
      if (window.location.pathname !== expected) {
        history.replaceState({}, "", expected);
      }
      return route;
    }

    function navigate(route) {
      const next = ROUTES[route] ? route : "overview";
      const path = routePath(next);
      if (window.location.pathname !== path) {
        history.pushState({}, "", path);
      }
      render(currentState, { forceView: true });
    }

    function cloneConfig(config) {
      const draft = JSON.parse(JSON.stringify(config || {}));
      draft.system = draft.system || {};
      draft.system.mode = draft.system.mode || "realtime";
      draft.system.market = draft.system.market || "cn";
      draft.system.capital_base = Number(draft.system.capital_base ?? 1000000);
      draft.system.loop_iterations = Number(draft.system.loop_iterations ?? 80);
      draft.system.poll_interval_seconds = Number(draft.system.poll_interval_seconds ?? 15);
      draft.system.timezone = draft.system.timezone || "Asia/Shanghai";
      draft.system.risk_budget = draft.system.risk_budget || {};
      draft.system.risk_budget.max_drawdown = Number(draft.system.risk_budget.max_drawdown ?? 0.12);
      draft.system.risk_budget.var_limit = Number(draft.system.risk_budget.var_limit ?? 0.08);
      draft.system.risk_budget.exposure_limit = Number(draft.system.risk_budget.exposure_limit ?? 1);

      draft.feeds = draft.feeds || {};
      draft.feeds.market = draft.feeds.market || {};
      draft.feeds.market.type = draft.feeds.market.type || "synthetic_cn";
      draft.feeds.market.symbols = Array.isArray(draft.feeds.market.symbols) ? draft.feeds.market.symbols : ["510300.SH", "600519.SH", "IH9999.CCFX"];
      draft.feeds.market.poll_interval_seconds = Number(draft.feeds.market.poll_interval_seconds ?? draft.system.poll_interval_seconds ?? 15);
      draft.feeds.market.token_env = draft.feeds.market.token_env || "TUSHARE_TOKEN";
      draft.feeds.market.fallback_provider = draft.feeds.market.fallback_provider || "easyquotation";
      draft.feeds.market.provider = draft.feeds.market.provider || "sina";

      draft.risk_engine = draft.risk_engine || {};
      draft.risk_engine.controls = draft.risk_engine.controls || {};
      draft.risk_engine.controls.kill_switch = Boolean(draft.risk_engine.controls.kill_switch);
      draft.risk_engine.controls.circuit_breaker = Number(draft.risk_engine.controls.circuit_breaker ?? 0.05);
      draft.risk_engine.controls.position_limit_pct = Number(draft.risk_engine.controls.position_limit_pct ?? 0.35);
      draft.risk_engine.controls.min_confidence = Number(draft.risk_engine.controls.min_confidence ?? 0.45);
      draft.risk_engine.controls.max_volatility = Number(draft.risk_engine.controls.max_volatility ?? 0.8);
      draft.risk_engine.controls.max_stock_position_pct = Number(draft.risk_engine.controls.max_stock_position_pct ?? 0.3);
      draft.risk_engine.controls.max_futures_contracts_per_symbol = Number(draft.risk_engine.controls.max_futures_contracts_per_symbol ?? 2);
      draft.risk_engine.controls.max_futures_margin_pct = Number(draft.risk_engine.controls.max_futures_margin_pct ?? 0.28);
      draft.risk_engine.controls.max_futures_notional_pct = Number(draft.risk_engine.controls.max_futures_notional_pct ?? 0.7);
      draft.risk_engine.controls.max_gross_exposure_pct = Number(draft.risk_engine.controls.max_gross_exposure_pct ?? 0.95);

      draft.strategy_factory = draft.strategy_factory || {};
      draft.strategy_factory.templates = Array.isArray(draft.strategy_factory.templates) ? draft.strategy_factory.templates : ["pair_trade", "trend_follow", "event_driven"];
      draft.strategy_factory.autogen = draft.strategy_factory.autogen || {};
      draft.strategy_factory.autogen.enabled = Boolean(draft.strategy_factory.autogen.enabled);
      draft.strategy_factory.autogen.max_candidates = Number(draft.strategy_factory.autogen.max_candidates ?? 12);

      draft.agents = draft.agents || {};
      draft.agents.registry = Array.isArray(draft.agents.registry) ? draft.agents.registry : [];
      draft.agents.registry = draft.agents.registry.map((agent) => ({
        id: agent.id,
        role: agent.role,
        enabled: Boolean(agent.enabled ?? true),
        capital_ratio: Number(agent.capital_ratio ?? 0)
      }));
      return draft;
    }

    function syncDraft(config, force = false) {
      if (!configDraft || force || !draftDirty) {
        configDraft = cloneConfig(config);
      }
    }

    function getNested(source, path, fallback = "") {
      const value = String(path).split(".").reduce((acc, key) => acc?.[key], source);
      return value ?? fallback;
    }

    function setNested(target, path, value) {
      const keys = String(path).split(".");
      let cursor = target;
      keys.slice(0, -1).forEach((key) => {
        if (!cursor[key] || typeof cursor[key] !== "object") cursor[key] = {};
        cursor = cursor[key];
      });
      cursor[keys[keys.length - 1]] = value;
    }

    async function fetchState() {
      if (fetchInFlight) return;
      fetchInFlight = true;
      const response = await fetch(`/api/state?ts=${Date.now()}`, {
        cache: "no-store",
        headers: { "Cache-Control": "no-store" }
      });
      try {
        if (!response.ok) throw new Error(`状态拉取失败 (${response.status})`);
        const payload = await response.json();
        currentState = payload;
        lastSyncAt = new Date();
        syncDraft(payload.config || {});
        render(payload);
      } finally {
        fetchInFlight = false;
      }
    }

    function startPolling() {
      if (poller !== null) return;
      poller = window.setInterval(() => {
        fetchState().catch((error) => setErrorStatus(error.message));
      }, POLL_MS);
    }

    function setErrorStatus(message) {
      statusBadge.dataset.status = "error";
      statusBadge.textContent = "异常";
      statusLine.textContent = message;
    }

    function formatClock(value) {
      if (!value) return "-";
      return value.toLocaleTimeString("zh-CN", { hour12: false });
    }

    function setTextIfChanged(node, value) {
      if (node.textContent !== value) {
        node.textContent = value;
      }
    }

    function render(state, options = {}) {
      const route = ensureRoute();
      const routeChanged = route !== lastRoute;
      renderNav(route);
      renderHeader(route, state);
      renderSidebar(state);
      renderNotice(state);
      renderView(route, state, { force: Boolean(options.forceView || routeChanged) });
      lastRoute = route;
      updateRunButton(state?.status || "idle");
    }

    function renderNav(route) {
      const html = Object.entries(ROUTES).map(([key, meta]) => `
        <button class="nav-btn ${key === route ? "active" : ""}" type="button" data-route="${key}">
          <strong>${meta.label}</strong>
          <span>${meta.brief}</span>
        </button>
      `).join("");
      if (html !== lastNavHtml) {
        nav.innerHTML = html;
        lastNavHtml = html;
      }
    }

    function renderHeader(route, state) {
      const meta = ROUTES[route];
      setTextIfChanged(routeEyebrow, meta.eyebrow);
      setTextIfChanged(routeTitle, meta.title);
      setTextIfChanged(routeSubtitle, meta.subtitle);
      const status = state?.status || "idle";
      if (statusBadge.dataset.status !== status) {
        statusBadge.dataset.status = status;
      }
      setTextIfChanged(statusBadge, translateStatus(status));
      const line = state?.summary?.generated_at
        ? `最新结果 ${formatDateTime(state.summary.generated_at)} · 已同步 ${formatClock(lastSyncAt)}`
        : lastSyncAt
          ? `状态已同步 ${formatClock(lastSyncAt)}`
          : "等待运行结果";
      setTextIfChanged(statusLine, line);
    }

    function renderSidebar(state) {
      const kpis = state?.summary?.kpis || {};
      const comparison = state?.comparison || null;
      const html = `
        <div class="eyebrow">Quick Look</div>
        <div class="kv-list">
          ${kv("总权益", formatValue(kpis.equity))}
          ${kv("已实现盈亏", formatSigned(kpis.realized_pnl))}
          ${kv("未实现盈亏", formatSigned(kpis.unrealized_pnl_total ?? kpis.futures_unrealized_pnl))}
          ${kv("成交笔数", formatValue(kpis.trade_count))}
          ${kv("相较上次", comparison ? `${formatSigned(comparison.return_pct_delta)}%` : "-")}
        </div>
        <p class="muted">当前快览</p>
      `;
      if (html !== lastSidebarHtml) {
        sidebarPanel.innerHTML = html;
        lastSidebarHtml = html;
      }
    }

    function renderNotice(state) {
      const hasError = Boolean(state?.last_error);
      const tone = hasError ? "error" : (state?.status === "running" || state?.status === "loading") ? "warning" : "normal";
      const summary = state?.summary || null;
      const modeValue = summary?.mode || state?.config?.system?.mode;
      const marketValue = summary?.market || state?.config?.system?.market;
      const feedType = state?.market_feed_status?.type || state?.config?.feeds?.market?.type || "synthetic_cn";
      const html = hasError
        ? `<strong>最近一次运行出现异常</strong><div class="muted">${escapeHtml(state.last_error)}</div>`
        : `<strong>当前上下文</strong><div class="meta-row">
            <div class="meta-chip"><span>模式</span><strong>${escapeHtml(translateMode(modeValue))}</strong></div>
            <div class="meta-chip"><span>市场</span><strong>${escapeHtml(translateMarket(marketValue))}</strong></div>
            <div class="meta-chip"><span>行情源</span><strong>${escapeHtml(translateFeedType(feedType))}</strong></div>
            <div class="meta-chip"><span>配置</span><strong>${escapeHtml(state?.active_config_path || state?.config_path || "-")}</strong></div>
          </div>${feedNotice(state)}`;
      if (notice.dataset.tone !== tone) {
        notice.dataset.tone = tone;
      }
      if (tone !== lastNoticeTone || html !== lastNoticeHtml) {
        notice.innerHTML = html;
        lastNoticeHtml = html;
        lastNoticeTone = tone;
      }
    }

    function renderView(route, state, options = {}) {
      if (route === "run" && draftDirty && !options.force) {
        return;
      }
      const html = renderRoute(route, state);
      if (options.force || html !== lastViewHtml) {
        view.innerHTML = html;
        lastViewHtml = html;
      }
    }

    function renderRoute(route, state) {
      if (route === "run") return renderRun(state);
      if (route === "agents") return renderAgents(state?.summary || null);
      if (route === "portfolio") return renderPortfolio(state?.summary || null);
      if (route === "history") return renderHistory(state);
      return renderOverview(state);
    }

    function renderOverview(state) {
      const summary = state?.summary;
      if (!summary) return empty("还没有运行结果", "先到“运行”页启动一次模拟，这里就会出现权益、风险和最新成交。");
      const kpis = summary.kpis || {};
      const perf = summary.performance || {};
      const holdings = [...(summary.positions?.stocks || [])].sort((a, b) => Number(b.market_value || 0) - Number(a.market_value || 0)).slice(0, 5);
      const fills = (summary.recent_fills || []).slice(0, 8);
      return `<div class="view">
        <div class="three">
          <section class="hero">
            <div>
              <div class="eyebrow">Capital Snapshot</div>
              <h3>当前组合权益</h3>
            </div>
            <div class="hero-value">
              <div class="hero-number">${formatValue(kpis.equity)}</div>
              <div class="hero-badge ${toneClass(formatSigned(perf.total_return_pct))}">${formatSigned(perf.total_return_pct)}%</div>
            </div>
            <div class="meta-row">
              ${meta("可用现金", formatValue(kpis.cash_available))}
              ${meta("总敞口", formatValue(kpis.gross_exposure))}
              ${meta("最大回撤", `${formatValue(perf.max_drawdown_pct)}%`)}
              ${meta("成交笔数", formatValue(kpis.trade_count))}
            </div>
          </section>
          <section class="panel">
            <div class="section-head"><div class="tag">立即判断</div></div>
            <div class="kv-list">
              ${kv("已实现盈亏", formatSigned(kpis.realized_pnl))}
              ${kv("未实现盈亏", formatSigned(kpis.unrealized_pnl_total ?? kpis.futures_unrealized_pnl))}
              ${kv("股票市值", formatValue(kpis.stock_market_value))}
              ${kv("杠杆率", formatValue(kpis.leverage_ratio))}
              ${kv("市场模式", `${translateMarket(summary.market)} / ${translateMode(summary.mode)}`)}
            </div>
          </section>
        </div>
        <section class="tiles">
          ${metric("期货保证金", formatValue(kpis.futures_margin_in_use), "当前保证金占用")}
          ${metric("总费用", formatValue(kpis.total_fees), "累计执行成本")}
          ${metric("波动率", `${formatValue(perf.volatility_pct)}%`, "收益波动强度")}
          ${metric("换手率", formatValue(perf.turnover_ratio), "资金轮换速度")}
        </section>
        <div class="three">
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">权益曲线</h3></div></div>
            ${curve(summary.equity_curve || [], "equity", "最高权益", "最低权益")}
          </section>
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">运行告警</h3></div></div>
            ${alerts(summary.alerts || [])}
          </section>
        </div>
        <div class="two">
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">当前主要持仓</h3></div></div>
            ${table(holdings, ["symbol", "quantity", "market_value", "unrealized_pnl"], ["代码", "数量", "市值", "未实现盈亏"])}
          </section>
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">最近成交</h3></div></div>
            ${table(fills, ["timestamp", "symbol", "effect", "quantity", "price", "agent_id"], ["时间", "代码", "动作", "数量", "价格", "智能体"])}
          </section>
        </div>
      </div>`;
    }

    function renderRun(state) {
      syncDraft(state?.config || {});
      const draft = configDraft || cloneConfig({});
      const summary = state?.summary || null;
      return `<div class="view">
        <div class="two">
          <section class="panel">
            <div class="section-head">
              <div>
                <h3 class="section-title">基础配置</h3>
              </div>
              <div class="btn-row">
                <button class="btn" data-action="reset-config">恢复配置</button>
                <button class="btn primary" data-action="save-config">保存配置</button>
              </div>
            </div>
            <div class="field-grid">
              ${selectField("运行模式", "system.mode", getNested(draft, "system.mode", "realtime"), [["simulation", "模拟"], ["realtime", "实时"]])}
              ${selectField("市场", "system.market", getNested(draft, "system.market", "cn"), [["cn", "中国市场"], ["us", "美国市场"]])}
              ${numberField("初始资金", "system.capital_base", getNested(draft, "system.capital_base", 1000000), "10000", "", "10000")}
              ${numberField("循环次数", "system.loop_iterations", getNested(draft, "system.loop_iterations", 80), "1", "", "1")}
              ${numberField("刷新间隔(秒)", "system.poll_interval_seconds", getNested(draft, "system.poll_interval_seconds", 15), "1", "", "1")}
              ${textField("时区", "system.timezone", getNested(draft, "system.timezone", "Asia/Shanghai"))}
            </div>
            <div class="section-head" style="margin-top:6px;">
              <div>
                <h3 class="section-title">风险预算</h3>
              </div>
            </div>
            <div class="field-grid">
              ${numberField("最大回撤", "system.risk_budget.max_drawdown", getNested(draft, "system.risk_budget.max_drawdown", 0.12), "0.01", "1", "0.01")}
              ${numberField("VaR 限制", "system.risk_budget.var_limit", getNested(draft, "system.risk_budget.var_limit", 0.08), "0.01", "1", "0.01")}
              ${numberField("暴露限制", "system.risk_budget.exposure_limit", getNested(draft, "system.risk_budget.exposure_limit", 1), "0.1", "3", "0.1")}
            </div>
          </section>
          <section class="panel">
            <div class="section-head">
              <div>
                <h3 class="section-title">运行状态</h3>
              </div>
            </div>
            <div class="kv-list">
              ${kv("基础配置", state?.config_path || "-")}
              ${kv("当前生效配置", state?.active_config_path || "-")}
              ${kv("模式", translateMode(summary?.mode || state?.config?.system?.mode))}
              ${kv("市场", translateMarket(summary?.market || state?.config?.system?.market))}
              ${kv("数据源", summary?.data_source?.market_feed_type || translateFeedType(state?.market_feed_status?.type))}
              ${kv("行情状态", state?.market_feed_status?.ready ? (state?.market_feed_status?.is_live ? "真实行情就绪" : "模拟/回放就绪") : "未就绪")}
              ${kv("上次同步", lastSyncAt ? formatClock(lastSyncAt) : "-")}
            </div>
          </section>
        </div>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3 class="section-title">风控参数</h3>
            </div>
          </div>
          <div class="field-grid">
            ${checkField("启用 Kill Switch", "risk_engine.controls.kill_switch", getNested(draft, "risk_engine.controls.kill_switch", false))}
            ${numberField("熔断阈值", "risk_engine.controls.circuit_breaker", getNested(draft, "risk_engine.controls.circuit_breaker", 0.05), "0.01", "0.5", "0.01")}
            ${numberField("仓位限制", "risk_engine.controls.position_limit_pct", getNested(draft, "risk_engine.controls.position_limit_pct", 0.35), "0.01", "1", "0.01")}
            ${numberField("最小置信度", "risk_engine.controls.min_confidence", getNested(draft, "risk_engine.controls.min_confidence", 0.45), "0", "1", "0.01")}
            ${numberField("最大波动率", "risk_engine.controls.max_volatility", getNested(draft, "risk_engine.controls.max_volatility", 0.8), "0.1", "10", "0.1")}
            ${numberField("最大股票仓位", "risk_engine.controls.max_stock_position_pct", getNested(draft, "risk_engine.controls.max_stock_position_pct", 0.3), "0.01", "1", "0.01")}
            ${numberField("单品种期货手数上限", "risk_engine.controls.max_futures_contracts_per_symbol", getNested(draft, "risk_engine.controls.max_futures_contracts_per_symbol", 2), "1", "", "1")}
            ${numberField("期货保证金上限", "risk_engine.controls.max_futures_margin_pct", getNested(draft, "risk_engine.controls.max_futures_margin_pct", 0.28), "0.01", "1", "0.01")}
            ${numberField("期货名义仓位上限", "risk_engine.controls.max_futures_notional_pct", getNested(draft, "risk_engine.controls.max_futures_notional_pct", 0.7), "0.01", "3", "0.01")}
            ${numberField("总风险敞口上限", "risk_engine.controls.max_gross_exposure_pct", getNested(draft, "risk_engine.controls.max_gross_exposure_pct", 0.95), "0.01", "3", "0.01")}
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3 class="section-title">策略工厂</h3>
            </div>
          </div>
          <div class="field-grid">
            ${checkField("启用自动生成", "strategy_factory.autogen.enabled", getNested(draft, "strategy_factory.autogen.enabled", false))}
            ${numberField("最大候选策略数", "strategy_factory.autogen.max_candidates", getNested(draft, "strategy_factory.autogen.max_candidates", 12), "1", "100", "1")}
            ${textField("策略模板(逗号分隔)", "strategy_factory.templates", (getNested(draft, "strategy_factory.templates", []) || []).join(", "), "list")}
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3 class="section-title">行情接入</h3>
            </div>
          </div>
          <div class="field-grid">
            ${selectField("行情源", "feeds.market.type", getNested(draft, "feeds.market.type", "synthetic_cn"), [["synthetic_cn", "模拟行情"], ["tushare_realtime", "Tushare 实时"], ["easyquotation_realtime", "EasyQuotation 实时"], ["csv_replay", "CSV 回放"]])}
            ${textField("标的列表(逗号分隔)", "feeds.market.symbols", (getNested(draft, "feeds.market.symbols", []) || []).join(", "), "list")}
            ${numberField("行情轮询秒数", "feeds.market.poll_interval_seconds", getNested(draft, "feeds.market.poll_interval_seconds", 15), "0", "", "1")}
            ${textField("Tushare Token 环境变量", "feeds.market.token_env", getNested(draft, "feeds.market.token_env", "TUSHARE_TOKEN"))}
            ${selectField("实时回退源", "feeds.market.fallback_provider", getNested(draft, "feeds.market.fallback_provider", "easyquotation"), [["easyquotation", "easyquotation"], ["none", "不回退"]])}
            ${selectField("EasyQuotation Provider", "feeds.market.provider", getNested(draft, "feeds.market.provider", "sina"), [["sina", "新浪"], ["tencent", "腾讯"]])}
          </div>
        </section>
        <section class="panel">
          <div class="section-head">
            <div>
              <h3 class="section-title">智能体配置</h3>
            </div>
            <button class="btn" data-action="add-agent">新增智能体</button>
          </div>
          ${agentConfig(getNested(draft, "agents.registry", []))}
        </section>
      </div>`;
    }

    function renderAgents(summary) {
      if (!summary) return empty("还没有智能体结果", "先运行一次模拟，这里才会出现智能体排行和 NAV 曲线。");
      const attr = summary.agent_attribution || {};
      const rank = attr.ranking || [];
      return `<div class="view">
        <div class="two">
          ${spotlight("当前最优智能体", attr.top_winner)}
          ${spotlight("当前最弱智能体", attr.top_loser)}
        </div>
        <section class="panel">
          <div class="section-head"><div><h3 class="section-title">智能体 NAV 曲线</h3></div></div>
          ${agentCurve(summary.agent_contribution_curves || {}, attr)}
        </section>
        <section class="panel">
          <div class="section-head"><div><h3 class="section-title">贡献排行</h3></div></div>
          ${table(rank, ["rank", "agent_id", "role", "nav", "return_pct", "net_pnl", "realized_pnl", "unrealized_pnl", "trade_count", "effect_breakdown"], ["排名", "智能体", "角色", "NAV", "收益率 %", "净盈亏", "已实现盈亏", "未实现盈亏", "成交笔数", "行为拆解"])}
        </section>
      </div>`;
    }

    function renderPortfolio(summary) {
      if (!summary) return empty("还没有持仓账本", "运行完成后，这里会单独展示持仓、盈亏和成交，不再和参数、历史混在一起。");
      const kpis = summary.kpis || {};
      const rank = summary.agent_attribution?.ranking || [];
      return `<div class="view">
        <section class="tiles">
          ${metric("组合权益", formatValue(kpis.equity), "账户总权益")}
          ${metric("已实现盈亏", formatSigned(kpis.realized_pnl), "已落地收益")}
          ${metric("未实现盈亏", formatSigned(kpis.unrealized_pnl_total ?? kpis.futures_unrealized_pnl), "浮动盈亏")}
          ${metric("股票市值", formatValue(kpis.stock_market_value), "股票仓位价值")}
          ${metric("可用现金", formatValue(kpis.cash_available), "当前可用资金")}
        </section>
        <div class="two">
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">股票持仓</h3></div></div>
            ${table(summary.positions?.stocks || [], ["symbol", "quantity", "avg_price", "last_price", "market_value", "unrealized_pnl"], ["代码", "数量", "均价", "现价", "市值", "未实现盈亏"])}
          </section>
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">期货持仓</h3></div></div>
            ${table(summary.positions?.futures || [], ["symbol", "long_qty", "short_qty", "last_price", "unrealized_pnl"], ["代码", "多头", "空头", "现价", "未实现盈亏"])}
          </section>
        </div>
        <section class="panel">
          <div class="section-head"><div><h3 class="section-title">智能体资金归因</h3></div></div>
          ${table(rank, ["agent_id", "role", "effective_capital_ratio", "nav", "net_pnl", "trade_count", "total_notional"], ["智能体", "角色", "资金占比", "NAV", "净盈亏", "成交笔数", "成交额"])}
        </section>
        <section class="panel">
          <div class="section-head"><div><h3 class="section-title">最近成交流水</h3></div></div>
          ${table(summary.recent_fills || [], ["timestamp", "symbol", "stock_name", "effect", "quantity", "price", "notional", "realized_pnl", "agent_id"], ["时间", "代码", "名称", "动作", "数量", "价格", "成交额", "已实现盈亏", "智能体"])}
        </section>
      </div>`;
    }

    function renderHistory(state) {
      const summary = state?.summary || null;
      const cmp = state?.comparison || null;
      return `<div class="view">
        <section class="tiles">
          ${metric("权益变化", cmp ? formatSigned(cmp.equity_delta) : "-", "相较上一轮")}
          ${metric("收益率变化", cmp ? formatSigned(cmp.return_pct_delta) : "-", "百分点变化")}
          ${metric("回撤变化", cmp ? formatSigned(cmp.max_drawdown_pct_delta) : "-", "百分点变化")}
          ${metric("成交笔数变化", cmp ? formatSigned(cmp.trade_count_delta) : "-", "相比上一轮")}
          ${metric("杠杆变化", cmp ? formatSigned(cmp.leverage_ratio_delta) : "-", "相比上一轮")}
        </section>
        <section class="panel">
          <div class="section-head"><div><h3 class="section-title">运行历史</h3></div></div>
          ${table(state?.history || [], ["run_id", "generated_at", "mode", "ticks_processed", "equity", "total_return_pct", "max_drawdown_pct", "trade_count"], ["运行 ID", "生成时间", "模式", "Tick 数", "总权益", "收益率 %", "最大回撤 %", "成交笔数"])}
        </section>
        <div class="two">
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">Ablation 对比</h3></div></div>
            ${ablation(summary?.ablation_report || null)}
          </section>
          <section class="panel">
            <div class="section-head"><div><h3 class="section-title">当前告警清单</h3></div></div>
            ${table(summary?.alerts || [], ["severity", "code", "agent_id", "message"], ["级别", "代码", "智能体", "说明"])}
          </section>
        </div>
      </div>`;
    }

    function empty(title, desc) {
      return `<div class="view"><section class="panel"><div class="section-head"><div><h3 class="section-title">${escapeHtml(title)}</h3><p class="muted">${escapeHtml(desc)}</p></div></div><p class="empty">当前页面会在第一次运行完成后自动填充。</p></section></div>`;
    }

    function kv(label, value) {
      return `<div class="kv"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
    }

    function meta(label, value) {
      return `<div class="meta-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
    }

    function metric(label, value, note) {
      return `<section class="metric"><span class="muted">${escapeHtml(label)}</span><strong class="${toneClass(value)}">${escapeHtml(value)}</strong><span class="muted">${escapeHtml(note)}</span></section>`;
    }

    function numberField(label, key, value, min, max, step) {
      const maxAttr = max ? `max="${max}"` : "";
      return `<div class="field"><span>${escapeHtml(label)}</span><input type="number" data-config-number="${escapeHtml(key)}" value="${escapeHtml(String(value))}" min="${escapeHtml(min)}" ${maxAttr} step="${escapeHtml(step)}"></div>`;
    }

    function textField(label, key, value, kind = "text") {
      const attr = kind === "list" ? "data-config-list" : "data-config";
      return `<div class="field"><span>${escapeHtml(label)}</span><input type="text" ${attr}="${escapeHtml(key)}" value="${escapeHtml(String(value))}"></div>`;
    }

    function selectField(label, key, value, options) {
      return `<div class="field"><span>${escapeHtml(label)}</span><select data-config="${escapeHtml(key)}">${options.map(([optionValue, optionLabel]) => `<option value="${escapeHtml(optionValue)}" ${String(value) === String(optionValue) ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`).join("")}</select></div>`;
    }

    function checkField(label, key, checked) {
      return `<label class="field check"><input type="checkbox" data-config-bool="${escapeHtml(key)}" ${checked ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
    }

    function agentConfig(agents) {
      if (!agents.length) return `<p class="empty">暂无智能体配置。</p>`;
      return `<div class="agent-list">${agents.map((agent) => `
        <div class="agent-row">
          <div class="field">
            <span>ID</span>
            <input type="text" data-agent-id="${escapeHtml(agent.id)}" value="${escapeHtml(agent.id)}">
          </div>
          <label class="check"><input type="checkbox" data-agent-enabled="${escapeHtml(agent.id)}" ${agent.enabled ? "checked" : ""}>启用</label>
          <div class="field"><span>资金配比</span><input type="number" min="0.01" max="1.00" step="0.01" data-agent-ratio="${escapeHtml(agent.id)}" value="${escapeHtml(String(agent.capital_ratio))}"></div>
          <div class="field">
            <span>角色</span>
            <select data-agent-role="${escapeHtml(agent.id)}">
              ${AVAILABLE_AGENT_ROLES.map(([value, label]) => `<option value="${escapeHtml(value)}" ${agent.role === value ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
            </select>
          </div>
          <button class="btn" type="button" data-agent-delete="${escapeHtml(agent.id)}">删除</button>
        </div>`).join("")}</div>`;
    }

    function spotlight(title, agent) {
      if (!agent) return `<section class="panel"><div class="section-head"><div><h3 class="section-title">${escapeHtml(title)}</h3><p class="muted">当前没有可展示结果。</p></div></div></section>`;
      return `<section class="panel">
        <div class="section-head"><div><h3 class="section-title">${escapeHtml(title)}</h3><p class="muted">${escapeHtml(translateRole(agent.role))}</p></div></div>
        <div class="hero-value"><div class="hero-number">${escapeHtml(agent.agent_id || "-")}</div></div>
        <div class="kv-list">
          ${kv("净盈亏", formatSigned(agent.net_pnl))}
          ${kv("NAV", formatValue(agent.nav))}
          ${kv("收益率", `${formatValue(agent.return_pct)}%`)}
          ${kv("成交笔数", formatValue(agent.trade_count))}
        </div>
      </section>`;
    }

    function alerts(list) {
      if (!list.length) return `<p class="empty">当前没有运行告警。</p>`;
      return `<div class="alerts">${list.map((item) => `
        <article class="alert">
          <div><span class="severity ${escapeHtml(item.severity || "info")}">${escapeHtml(translateSeverity(item.severity))}</span></div>
          <strong>${escapeHtml(item.code || "告警")}</strong>
          <div>${escapeHtml(item.message || "-")}</div>
        </article>`).join("")}</div>`;
    }

    function curve(points, key, maxLabel, minLabel) {
      if (!points.length) return `<p class="empty">暂无曲线数据。</p>`;
      const width = 980;
      const height = 240;
      const pad = 24;
      const values = points.map((point) => Number(point[key] || 0));
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (min === max) { min -= 1; max += 1; }
      const spread = Math.max(max - min, 1);
      const step = (width - pad * 2) / Math.max(points.length - 1, 1);
      const poly = points.map((point, index) => {
        const x = pad + index * step;
        const y = height - pad - ((Number(point[key] || 0) - min) / spread) * (height - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
      return `<div class="chart"><svg viewBox="0 0 ${width} ${height}" width="100%" height="250" preserveAspectRatio="none">
        <polyline fill="none" stroke="#67e8f9" stroke-width="3" points="${poly}"></polyline>
        <text x="${pad}" y="18" fill="#94a3b8" font-size="12">${escapeHtml(maxLabel)} ${escapeHtml(formatValue(max))}</text>
        <text x="${pad}" y="${height - 8}" fill="#94a3b8" font-size="12">${escapeHtml(minLabel)} ${escapeHtml(formatValue(min))}</text>
        <text x="${width - 120}" y="18" fill="#94a3b8" font-size="12">点数 ${points.length}</text>
      </svg></div>`;
    }

    function agentCurve(curves, attr) {
      const ranking = attr?.ranking || [];
      const ids = ranking.slice(0, 4).map((row) => row.agent_id).filter(Boolean);
      const selected = (ids.length ? ids : Object.keys(curves || {}).slice(0, 4)).map((id) => ({ id, points: curves[id] || [] })).filter((item) => item.points.length);
      if (!selected.length) return `<p class="empty">暂无智能体 NAV 曲线。</p>`;
      const width = 980;
      const height = 240;
      const pad = 26;
      const colors = ["#5eead4", "#67e8f9", "#fbbf24", "#fb7185"];
      const values = selected.flatMap((item) => item.points.map((point) => Number(point.nav ?? 0)));
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (min === max) { min -= 1; max += 1; }
      const spread = Math.max(max - min, 1);
      const longest = Math.max(...selected.map((item) => item.points.length));
      const step = (width - pad * 2) / Math.max(longest - 1, 1);
      const lines = selected.map((item, idx) => {
        const pts = item.points.map((point, index) => {
          const x = pad + index * step;
          const y = height - pad - ((Number(point.nav ?? 0) - min) / spread) * (height - pad * 2);
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(" ");
        return `<polyline fill="none" stroke="${colors[idx % colors.length]}" stroke-width="3" points="${pts}"></polyline>`;
      }).join("");
      const legends = selected.map((item, idx) => `<text x="${pad}" y="${20 + idx * 18}" fill="${colors[idx % colors.length]}" font-size="12">${escapeHtml(item.id)}</text>`).join("");
      return `<div class="chart"><svg viewBox="0 0 ${width} ${height}" width="100%" height="250" preserveAspectRatio="none">
        ${lines}${legends}
        <text x="${width - 170}" y="18" fill="#94a3b8" font-size="12">最高 NAV ${escapeHtml(formatValue(max))}</text>
        <text x="${width - 170}" y="${height - 8}" fill="#94a3b8" font-size="12">最低 NAV ${escapeHtml(formatValue(min))}</text>
      </svg></div>`;
    }

    function feedNotice(state) {
      const feedStatus = state?.market_feed_status || {};
      if (!feedStatus.message) return "";
      const className = feedStatus.ready ? "muted" : "bad";
      return `<div class="${className}">${escapeHtml(feedStatus.message)}</div>`;
    }

    function ablation(report) {
      if (!report) return `<p class="empty">暂无 ablation 结果。</p>`;
      const base = report.baseline || {};
      const best = report.best_disable_candidate || null;
      return `${table([
        { item: "基准收益率", value: `${formatValue(base.total_return_pct)}%` },
        { item: "基准最大回撤", value: `${formatValue(base.max_drawdown_pct)}%` },
        { item: "基准成交笔数", value: formatValue(base.trade_count) },
        { item: "最佳移除候选", value: best ? `${best.disabled_agent_id} / 收益变化 ${formatSigned(best.return_pct_delta)} / 回撤变化 ${formatSigned(best.max_drawdown_pct_delta)}` : "-" }
      ], ["item", "value"], ["项目", "结果"])}
      <div style="height:14px;"></div>
      ${table(report.scenarios || [], ["disabled_agent_id", "disabled_role", "total_return_pct", "return_pct_delta", "max_drawdown_pct", "max_drawdown_pct_delta", "trade_count"], ["移除智能体", "角色", "收益率 %", "收益率变化", "最大回撤 %", "回撤变化", "成交笔数"])}`;
    }

    function table(rows, keys, headers) {
      if (!rows || !rows.length) return `<p class="empty">暂无数据。</p>`;
      const head = headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("");
      const body = rows.map((row) => `<tr>${keys.map((key) => `<td>${escapeHtml(cell(key, row[key]))}</td>`).join("")}</tr>`).join("");
      return `<div class="table-wrap"><table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    function cell(key, value) {
      if (key === "effect") return translateEffect(value);
      if (key === "role" || key === "disabled_role") return translateRole(value);
      if (key === "mode") return translateMode(value);
      if (key === "market") return translateMarket(value);
      if (key === "severity") return translateSeverity(value);
      if (key === "timestamp" || key === "generated_at") return formatDateTime(value);
      if (key === "effect_breakdown") return effectBreakdown(value);
      return formatValue(value);
    }

    function collectOverrides() {
      const draft = configDraft || cloneConfig(currentState?.config || {});
      return {
        system: { loop_iterations: Number(getNested(draft, "system.loop_iterations", 0) || 0) },
        risk_controls: {
          max_stock_position_pct: Number(getNested(draft, "risk_engine.controls.max_stock_position_pct", 0) || 0),
          max_futures_contracts_per_symbol: Number(getNested(draft, "risk_engine.controls.max_futures_contracts_per_symbol", 0) || 0),
          max_futures_margin_pct: Number(getNested(draft, "risk_engine.controls.max_futures_margin_pct", 0) || 0),
          max_futures_notional_pct: Number(getNested(draft, "risk_engine.controls.max_futures_notional_pct", 0) || 0),
          max_gross_exposure_pct: Number(getNested(draft, "risk_engine.controls.max_gross_exposure_pct", 0) || 0)
        },
        agents: getNested(draft, "agents.registry", []).map((agent) => ({ id: agent.id, enabled: Boolean(agent.enabled), capital_ratio: Number(agent.capital_ratio || 0) }))
      };
    }

    function buildAgentId(role) {
      const registry = getNested(configDraft, "agents.registry", []);
      const prefix = String(role || "agent").replaceAll("_", "-");
      let index = registry.filter((agent) => String(agent.role) === String(role)).length + 1;
      let candidate = `${prefix}-${index}`;
      while (registry.some((agent) => agent.id === candidate)) {
        index += 1;
        candidate = `${prefix}-${index}`;
      }
      return candidate;
    }

    function addAgent() {
      syncDraft(currentState?.config || {}, false);
      const role = "mean_reversion";
      const next = {
        id: buildAgentId(role),
        role,
        enabled: true,
        capital_ratio: 0.1
      };
      configDraft.agents.registry.push(next);
      draftDirty = true;
      render(currentState, { forceView: true });
      statusLine.textContent = `已新增智能体 ${next.id}`;
    }

    function removeAgent(agentId) {
      const registry = configDraft?.agents?.registry || [];
      const nextRegistry = registry.filter((agent) => agent.id !== agentId);
      if (nextRegistry.length === registry.length) return;
      configDraft.agents.registry = nextRegistry;
      draftDirty = true;
      render(currentState, { forceView: true });
      statusLine.textContent = `已删除智能体 ${agentId}`;
    }

    async function saveConfig() {
      statusLine.textContent = "正在保存配置...";
      const response = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configDraft || cloneConfig(currentState?.config || {}))
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "保存配置失败");
      currentState = payload.state || currentState;
      lastSyncAt = new Date();
      draftDirty = false;
      syncDraft(currentState?.config || {}, true);
      render(currentState, { forceView: true });
      statusLine.textContent = `配置已保存 · 已同步 ${formatClock(lastSyncAt)}`;
    }

    async function runSimulation() {
      updateRunButton("running");
      statusBadge.dataset.status = "running";
      statusBadge.textContent = "运行中";
      statusLine.textContent = "正在后台启动模拟...";
      try {
        const response = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(collectOverrides())
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "启动失败");
        draftDirty = false;
        currentState = payload;
        lastSyncAt = new Date();
        syncDraft(payload.config || {}, true);
        render(payload);
        startPolling();
      } catch (error) {
        setErrorStatus(error.message);
        updateRunButton("error");
      }
    }

    async function disableLoserAndRun() {
      const loser = currentState?.summary?.agent_attribution?.top_loser;
      if (!loser?.agent_id) {
        statusLine.textContent = "当前没有可关闭的最弱智能体。";
        return;
      }
      if (loser.agent_id === "risk-engine") {
        statusLine.textContent = "当前最弱对象是风控引擎，不能直接禁用。";
        return;
      }
      syncDraft(currentState?.config || {});
      const agent = (configDraft?.agents?.registry || []).find((item) => item.id === loser.agent_id);
      if (!agent) {
        statusLine.textContent = `找不到智能体 ${loser.agent_id} 的配置。`;
        return;
      }
      agent.enabled = false;
      draftDirty = true;
      render(currentState);
      statusLine.textContent = `已禁用 ${loser.agent_id}，正在重新运行。`;
      await runSimulation();
    }

    function updateRunButton(status) {
      const running = status === "running" || status === "loading";
      runButton.disabled = running;
      runButton.textContent = running ? "运行中..." : "运行模拟";
    }

    function formatValue(value) {
      if (typeof value === "number") {
        return Number.isInteger(value) ? value.toLocaleString("zh-CN") : value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
      }
      if (value === null || value === undefined || value === "") return "-";
      return String(value);
    }

    function formatSigned(value) {
      if (value === null || value === undefined || value === "") return "-";
      const n = Number(value || 0);
      return n > 0 ? `+${formatValue(n)}` : formatValue(n);
    }

    function formatDateTime(value) {
      return value ? String(value).replace("T", " ") : "-";
    }

    function toneClass(value) {
      const text = String(value || "");
      if (text.startsWith("+")) return "good";
      if (text.startsWith("-")) return "bad";
      return "";
    }

    function effectBreakdown(value) {
      const entries = Object.entries(value || {});
      if (!entries.length) return "-";
      return entries.sort((a, b) => String(a[0]).localeCompare(String(b[0]))).map(([effect, count]) => `${translateEffect(effect)} x${count}`).join(" / ");
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function translateStatus(value) {
      return { idle: "待机", running: "运行中", success: "成功", error: "异常", loading: "加载中" }[value] || value || "-";
    }

    function translateRole(value) {
      return {
        news_event: "新闻事件",
        reactive: "反应式交易",
        swing: "波段交易",
        futures_hedge: "期货对冲",
        mean_reversion: "均值回归",
        breakout: "突破交易",
        fundamental: "基本面精选",
        risk_engine: "风控引擎"
      }[value] || value || "-";
    }

    function translateEffect(value) {
      return { buy_stock: "买入股票", sell_stock: "卖出股票", open_long: "开多", close_long: "平多", open_short: "开空", close_short: "平空" }[value] || value || "-";
    }

    function translateSeverity(value) {
      return { info: "提示", warning: "警告", critical: "严重" }[value] || value || "-";
    }

    function translateMode(value) {
      return { simulation: "模拟", realtime: "实时", backtest: "回测" }[value] || value || "-";
    }

    function translateMarket(value) {
      return { cn: "中国市场", us: "美国市场" }[value] || value || "-";
    }

    function translateFeedType(value) {
      return {
        synthetic_cn: "模拟行情",
        tushare_realtime: "Tushare 实时",
        easyquotation_realtime: "EasyQuotation 实时",
        csv_replay: "CSV 回放"
      }[value] || value || "-";
    }

    document.addEventListener("click", (event) => {
      const routeBtn = event.target.closest("[data-route]");
      if (routeBtn) {
        navigate(routeBtn.getAttribute("data-route"));
        return;
      }

      const deleteBtn = event.target.closest("[data-agent-delete]");
      if (deleteBtn) {
        removeAgent(deleteBtn.getAttribute("data-agent-delete"));
        return;
      }

      const actionBtn = event.target.closest("[data-action]");
      if (!actionBtn) return;
      const action = actionBtn.getAttribute("data-action");
      if (action === "run") runSimulation().catch((error) => setErrorStatus(error.message));
      if (action === "refresh") {
        statusLine.textContent = "正在刷新状态...";
        fetchState().catch((error) => setErrorStatus(error.message));
      }
      if (action === "disable-loser") disableLoserAndRun().catch((error) => setErrorStatus(error.message));
      if (action === "add-agent") addAgent();
      if (action === "save-config") saveConfig().catch((error) => setErrorStatus(error.message));
      if (action === "reset-config") {
        syncDraft(currentState?.config || {}, true);
        draftDirty = false;
        render(currentState, { forceView: true });
      }
    });

    document.addEventListener("input", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      syncDraft(currentState?.config || {}, false);
      if (target.matches("[data-config]")) {
        setNested(configDraft, target.getAttribute("data-config"), target.value);
        draftDirty = true;
      }
      if (target.matches("[data-config-number]")) {
        setNested(configDraft, target.getAttribute("data-config-number"), Number(target.value));
        draftDirty = true;
      }
      if (target.matches("[data-config-list]")) {
        const values = String(target.value).split(",").map((item) => item.trim()).filter(Boolean);
        setNested(configDraft, target.getAttribute("data-config-list"), values);
        draftDirty = true;
      }
      if (target.matches("[data-config-bool]")) {
        setNested(configDraft, target.getAttribute("data-config-bool"), target.checked);
        draftDirty = true;
      }
      if (target.matches("[data-agent-enabled]")) {
        const agent = configDraft.agents.registry.find((item) => item.id === target.getAttribute("data-agent-enabled"));
        if (agent) {
          agent.enabled = target.checked;
          draftDirty = true;
        }
      }
      if (target.matches("[data-agent-ratio]")) {
        const agent = configDraft.agents.registry.find((item) => item.id === target.getAttribute("data-agent-ratio"));
        if (agent) {
          agent.capital_ratio = Number(target.value);
          draftDirty = true;
        }
      }
      if (target.matches("[data-agent-role]")) {
        const agent = configDraft.agents.registry.find((item) => item.id === target.getAttribute("data-agent-role"));
        if (agent) {
          agent.role = target.value;
          draftDirty = true;
        }
      }
    });

    document.addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.matches("[data-agent-id]")) {
        syncDraft(currentState?.config || {}, false);
        const agent = configDraft.agents.registry.find((item) => item.id === target.getAttribute("data-agent-id"));
        const nextId = String(target.value || "").trim();
        if (agent && nextId) {
          agent.id = nextId;
          draftDirty = true;
          render(currentState, { forceView: true });
        }
      }
    });

    window.addEventListener("popstate", () => render(currentState, { forceView: true }));

    ensureRoute();
    fetchState().catch((error) => {
      setErrorStatus(error.message);
      render(null);
    });
    startPolling();
  
