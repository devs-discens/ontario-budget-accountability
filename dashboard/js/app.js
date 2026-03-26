/**
 * App Controller — manages tabs, search, info panel, and cross-view linking.
 */
const App = (function () {
    let currentTab = 'revenue';
    let allData = null;

    async function init() {
        showLoading();

        try {
            allData = await DataLoader.loadAll();
            console.log('Data loaded:', {
                revenue: !!allData.revenue,
                expenses: !!allData.expenses,
                contracts: !!allData.contracts,
                companies: !!allData.companies,
                people: !!allData.people,
                connections: !!allData.connections,
            });
        } catch (e) {
            console.error('Failed to load data:', e);
            allData = {};
        }

        // Initialize views — each in its own try/catch so one failure doesn't block others
        try {
            if (allData.revenue) RevenueView.init(allData.revenue);
            else console.warn('No revenue data');
        } catch (e) { console.error('RevenueView init failed:', e); }

        try {
            if (allData.expenses) ExpenseView.init(allData.expenses, allData);
            else console.warn('No expenses data');
        } catch (e) { console.error('ExpenseView init failed:', e); }

        try {
            NetworkView.init(allData);
        } catch (e) { console.error('NetworkView init failed:', e); }

        try {
            if (allData.revenue && allData.expenses) {
                FlowView.init(document.getElementById('flow-chart'), allData);
            } else console.warn('No revenue/expenses for FlowView');
        } catch (e) { console.error('FlowView init failed:', e); }

        try {
            LedgerView.init(allData);
        } catch (e) { console.error('LedgerView init failed:', e); }

        bindTabs();
        bindInfoPanel();
        bindSearch();
        hideLoading();

        // Render active tab — Ledger is the default view
        switchTab('ledger');
    }

    function showLoading() {
        document.querySelectorAll('.chart-area').forEach(el => {
            if (!el.querySelector('.loading-msg') && !el.querySelector('svg') && !el.querySelector('.empty-state')) {
                el.innerHTML = '<div class="loading-msg">Loading data\u2026</div>';
            }
        });
    }

    function hideLoading() {
        document.querySelectorAll('.loading-msg').forEach(el => el.remove());
    }

    function bindTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                switchTab(this.dataset.tab);
            });
        });
    }

    function switchTab(tab) {
        currentTab = tab;

        // Update nav
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        const activeBtn = document.querySelector(`.tab-btn[data-tab="${tab}"]`);
        if (activeBtn) activeBtn.classList.add('active');

        // Show/hide panels
        document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('active'));
        const tabMap = {
            ledger: 'view-ledger',
            revenue: 'view-revenue',
            spending: 'view-spending',
            network: 'view-network',
            flow: 'view-flow',
        };
        const panel = document.getElementById(tabMap[tab]);
        if (panel) panel.classList.add('active');

        // Trigger resize for the new tab so SVG fits
        requestAnimationFrame(() => {
            switch (tab) {
                case 'ledger': LedgerView.render(); break;
                case 'revenue': RevenueView.render(); break;
                case 'spending': ExpenseView.render(); break;
                case 'network': NetworkView.render(); break;
                case 'flow': FlowView.render(); break;
            }
        });
    }

    function bindInfoPanel() {
        const panel = document.getElementById('info-panel');
        const toggle = document.getElementById('info-panel-toggle');
        toggle.addEventListener('click', function () {
            panel.classList.toggle('collapsed');
        });
    }

    function setInfoPanel(title, bodyHtml) {
        const panel = document.getElementById('info-panel');
        const titleEl = document.getElementById('info-title');
        const bodyEl = document.getElementById('info-body');

        titleEl.textContent = title;
        bodyEl.innerHTML = bodyHtml;

        // Expand if collapsed
        if (panel.classList.contains('collapsed')) {
            panel.classList.remove('collapsed');
        }
    }

    function bindSearch() {
        const input = document.getElementById('global-search');
        const dropdown = document.getElementById('search-results');

        input.addEventListener('input', function () {
            const q = this.value.trim();
            if (q.length < 2) {
                dropdown.classList.remove('active');
                dropdown.innerHTML = '';
                return;
            }

            const results = DataLoader.search(q);
            if (results.length === 0) {
                dropdown.classList.remove('active');
                return;
            }

            dropdown.innerHTML = results.map(r => `
                <div class="search-result-item" data-type="${r.type}" data-id="${r.id}">
                    <span class="result-type">${r.type}</span>
                    ${r.name}
                </div>
            `).join('');
            dropdown.classList.add('active');

            dropdown.querySelectorAll('.search-result-item').forEach(item => {
                item.addEventListener('click', function () {
                    handleSearchResult(this.dataset.type, this.dataset.id);
                    dropdown.classList.remove('active');
                    input.value = '';
                });
            });
        });

        // Close dropdown on click outside
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.header-search')) {
                dropdown.classList.remove('active');
            }
        });
    }

    function handleSearchResult(type, id) {
        switch (type) {
            case 'company':
                switchTab('network');
                setTimeout(() => NetworkView.focusOnEntity(id), 300);
                break;
            case 'person':
                switchTab('network');
                setTimeout(() => NetworkView.focusOnEntity(id), 300);
                break;
            case 'contract':
                switchTab('spending');
                break;
            case 'sector':
                switchTab('spending');
                setTimeout(() => ExpenseView.focusSector(id), 100);
                break;
            case 'subcategory':
                switchTab('spending');
                break;
        }
    }

    function switchToNetworkFor(entityId) {
        switchTab('network');
        setTimeout(() => NetworkView.focusOnEntity(entityId), 300);
    }

    /**
     * Format a number as currency (e.g., $1.2B, $450M, $12K).
     */
    function formatCurrency(val) {
        if (val == null || isNaN(val)) return '$0';
        const abs = Math.abs(val);
        if (abs >= 1e9) return '$' + (val / 1e9).toFixed(1) + 'B';
        if (abs >= 1e6) return '$' + (val / 1e6).toFixed(0) + 'M';
        if (abs >= 1e3) return '$' + (val / 1e3).toFixed(0) + 'K';
        return '$' + val.toFixed(0);
    }

    /**
     * Format as percentage.
     */
    function formatPercent(val) {
        if (val == null || isNaN(val)) return '0%';
        return val.toFixed(1) + '%';
    }

    // Boot
    document.addEventListener('DOMContentLoaded', init);

    return {
        switchTab,
        switchToNetworkFor,
        setInfoPanel,
        formatCurrency,
        formatPercent,
    };
})();
