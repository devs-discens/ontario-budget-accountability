/**
 * Accountability Ledger — searchable, filterable, sortable table of every spending decision.
 * Joins contracts + companies + connections + people into flat rows.
 */
const LedgerView = (function () {
    let allData = null;
    let rows = [];
    let filteredRows = [];
    let sortCol = 'amount';
    let sortDir = -1; // -1 = descending
    let filters = {
        search: '',
        sector: 'all',
        decisionType: 'all',
        flaggedOnly: false,
        connectionStrength: 'all',
    };
    let quickFilter = null; // 'flagged', 'sole-source', 'insider', or null

    // Map sector IDs to display names
    const SECTOR_LABELS = {
        'transit-transportation': 'Transit',
        'energy': 'Energy',
        'health': 'Health',
        'consulting': 'Consulting',
        'skills-development': 'Skills Dev',
        'manufacturing': 'Manufacturing',
        'other': 'Other',
        'transit': 'Transit',
    };

    // Determine decision type from contract and company data
    function inferDecisionType(contract, companies) {
        const name = (contract.name || '').toLowerCase();
        const notes = (contract.notes || '').toLowerCase();
        const id = (contract.id || '').toLowerCase();

        if (name.includes('sole-source') || notes.includes('sole-source') || notes.includes('sole source')) return 'sole-source';
        if (id.includes('sdf-') || contract.sector === 'skills-development') return 'ministerial-override';
        if (name.includes('subsidy') || id.includes('subsidy')) return 'legislative';

        // Check if any company has strong+ political connections — might be a progressive P3
        const hasStrongConn = companies.some(c => c.connection_strength === 'very_strong' || c.connection_strength === 'strong');
        // Check for P3/DBFM/DBFOM indicators
        if (name.includes('dbfm') || name.includes('dbfom') || name.includes('30yr') || name.includes('30+15yr') || name.includes('p3')) {
            return hasStrongConn ? 'progressive-p3' : 'competitive-bid';
        }

        // If IO/Metrolinx source URL or standard procurement
        if ((contract.source_url || '').includes('infrastructureontario.ca') || (contract.source_url || '').includes('metrolinx.com')) {
            return 'competitive-bid';
        }

        // If there's a very strong connection and it's not IO procurement, flag it
        if (hasStrongConn) return 'ministerial-override';

        return 'competitive-bid';
    }

    // Determine decision maker
    function inferDecisionMaker(contract) {
        const url = (contract.source_url || '').toLowerCase();
        const name = (contract.name || '').toLowerCase();
        const sector = contract.sector || '';

        if (url.includes('infrastructureontario.ca')) return 'IO';
        if (url.includes('metrolinx.com') || name.includes('go ') || name.includes('go-')) return 'Metrolinx';
        if (sector === 'skills-development') return 'Minister';
        if (sector === 'energy' && (name.includes('opg') || name.includes('darlington') || name.includes('pickering'))) return 'OPG';
        if (name.includes('bruce power')) return 'Bruce Power';
        if (name.includes('hydro one') || name.includes('transmission')) return 'Hydro One';
        if (name.includes('subsidy') || sector === 'manufacturing') return 'Cabinet';
        if (name.includes('highway') || name.includes('hwy')) return 'MTO';
        return 'Government';
    }

    // Determine flags for a contract row
    function getFlags(contract, companies, connectedPeople) {
        const flags = [];
        const name = (contract.name || '').toLowerCase();
        const notes = (contract.notes || '').toLowerCase();
        const id = (contract.id || '').toLowerCase();

        // AG flagged
        if (notes.includes('auditor general') || notes.includes('ag found') || notes.includes('ag said') ||
            (contract.source_url || '').includes('auditor-general')) {
            flags.push({ type: 'ag', label: 'AG', title: 'Auditor General flagged' });
        }

        // OPP investigation
        if (notes.includes('opp') || contract.status === 'fraud-investigation') {
            flags.push({ type: 'opp', label: 'OPP', title: 'OPP investigation' });
        }

        // Integrity Commissioner
        if (connectedPeople.some(p => p.integrity_violations) ||
            notes.includes('integrity commissioner') || notes.includes('integrity violation')) {
            flags.push({ type: 'integrity', label: 'IC', title: 'Integrity Commissioner finding' });
        }

        // Sole source
        if (name.includes('sole-source') || notes.includes('sole-source') || notes.includes('sole source')) {
            flags.push({ type: 'sole-source', label: 'SS', title: 'Sole-source contract' });
        }

        // Default judgment / fraud
        if (contract.status === 'default-judgment' || notes.includes('fraud') || notes.includes('default judgment')) {
            flags.push({ type: 'fraud', label: 'FRAUD', title: 'Fraud / default judgment' });
        }

        return flags;
    }

    function buildRows() {
        rows = [];
        if (!allData || !allData.contracts || !allData.contracts.contracts) return;

        const contractsList = allData.contracts.contracts;
        const companiesMap = {};
        const peopleMap = {};
        const edgesByNode = {};

        // Build company index
        if (allData.companies && allData.companies.companies) {
            allData.companies.companies.forEach(c => { companiesMap[c.id] = c; });
        }

        // Build people index
        if (allData.people && allData.people.people) {
            allData.people.people.forEach(p => { peopleMap[p.id] = p; });
        }

        // Build edges index
        const edgeList = allData.connections && (allData.connections.edges || allData.connections.connections);
        if (edgeList) {
            edgeList.forEach(e => {
                if (!edgesByNode[e.from]) edgesByNode[e.from] = [];
                edgesByNode[e.from].push(e);
                if (!edgesByNode[e.to]) edgesByNode[e.to] = [];
                edgesByNode[e.to].push(e);
            });
        }

        contractsList.forEach(contract => {
            // Get companies for this contract
            const companyIds = contract.companies || [];
            const companyObjects = companyIds.map(id => companiesMap[id]).filter(Boolean);

            // Get all connected people (lobbyists) for these companies
            const connectedPeople = [];
            const connectedPeopleIds = new Set();
            companyObjects.forEach(company => {
                if (company.lobbyists) {
                    company.lobbyists.forEach(pid => {
                        if (!connectedPeopleIds.has(pid)) {
                            connectedPeopleIds.add(pid);
                            const person = peopleMap[pid];
                            if (person) connectedPeople.push(person);
                        }
                    });
                }
            });

            // Also check connections.json edges for any people connected to these companies
            companyIds.forEach(compId => {
                const edges = edgesByNode[compId] || [];
                edges.forEach(edge => {
                    const otherId = edge.from === compId ? edge.to : edge.from;
                    const person = peopleMap[otherId];
                    if (person && !connectedPeopleIds.has(otherId)) {
                        connectedPeopleIds.add(otherId);
                        connectedPeople.push(person);
                    }
                });
            });

            // Determine strongest connection
            let strongestConnection = 'none';
            const strengthOrder = ['none', 'weak', 'moderate', 'strong', 'very_strong'];
            companyObjects.forEach(company => {
                const idx = strengthOrder.indexOf(company.connection_strength || 'none');
                const curIdx = strengthOrder.indexOf(strongestConnection);
                if (idx > curIdx) strongestConnection = company.connection_strength;
            });

            // Recipient: first company name or contract name
            const recipientCompany = companyObjects[0];
            const recipientName = recipientCompany ? recipientCompany.name : (companyIds[0] || contract.name);

            const decisionType = inferDecisionType(contract, companyObjects);
            const decisionMaker = inferDecisionMaker(contract);
            const flags = getFlags(contract, companyObjects, connectedPeople);

            rows.push({
                id: contract.id,
                amount: contract.value,
                recipient: recipientName,
                recipientId: companyIds[0] || null,
                allCompanies: companyObjects,
                allCompanyNames: companyObjects.map(c => c.name),
                sector: contract.sector || 'other',
                sectorLabel: SECTOR_LABELS[contract.sector] || contract.sector || 'Other',
                decisionType: decisionType,
                decisionMaker: decisionMaker,
                connectedPeople: connectedPeople,
                connectionStrength: strongestConnection,
                flags: flags,
                sourceUrl: contract.source_url || '',
                contract: contract,
                notes: contract.notes || '',
                status: contract.status || '',
                donationsPC: companyObjects.reduce((sum, c) => sum + (c.donations_pc || 0), 0),
            });
        });
    }

    function applyFilters() {
        filteredRows = rows.filter(row => {
            // Quick filter (from clicking summary stats)
            if (quickFilter === 'flagged' && row.flags.length === 0) return false;
            if (quickFilter === 'sole-source') {
                const isSS = row.decisionType === 'sole-source' || row.flags.some(f => f.type === 'sole-source');
                if (!isSS) return false;
            }
            if (quickFilter === 'insider') {
                const isInsider = row.connectionStrength === 'strong' || row.connectionStrength === 'very_strong' || row.connectionStrength === 'moderate';
                if (!isInsider) return false;
            }

            // Text search
            if (filters.search) {
                const q = filters.search.toLowerCase();
                const searchable = [
                    row.recipient,
                    row.contract.name,
                    row.notes,
                    ...row.connectedPeople.map(p => p.name),
                    ...row.allCompanyNames,
                ].join(' ').toLowerCase();
                if (!searchable.includes(q)) return false;
            }

            // Sector
            if (filters.sector !== 'all' && row.sector !== filters.sector) return false;

            // Decision type
            if (filters.decisionType !== 'all' && row.decisionType !== filters.decisionType) return false;

            // Flagged only
            if (filters.flaggedOnly && row.flags.length === 0) return false;

            // Connection strength
            if (filters.connectionStrength !== 'all') {
                const strongEnough = filters.connectionStrength === 'strong'
                    ? (row.connectionStrength === 'strong' || row.connectionStrength === 'very_strong')
                    : row.connectionStrength === filters.connectionStrength;
                if (!strongEnough) return false;
            }

            return true;
        });

        // Sort
        filteredRows.sort((a, b) => {
            let av, bv;
            switch (sortCol) {
                case 'amount':
                    av = a.amount || 0;
                    bv = b.amount || 0;
                    break;
                case 'recipient':
                    av = a.recipient.toLowerCase();
                    bv = b.recipient.toLowerCase();
                    return sortDir * av.localeCompare(bv);
                case 'sector':
                    av = a.sectorLabel.toLowerCase();
                    bv = b.sectorLabel.toLowerCase();
                    return sortDir * av.localeCompare(bv);
                case 'decisionType':
                    av = a.decisionType;
                    bv = b.decisionType;
                    return sortDir * av.localeCompare(bv);
                case 'decisionMaker':
                    av = a.decisionMaker;
                    bv = b.decisionMaker;
                    return sortDir * av.localeCompare(bv);
                case 'connections':
                    av = a.connectedPeople.length;
                    bv = b.connectedPeople.length;
                    break;
                case 'flags':
                    av = a.flags.length;
                    bv = b.flags.length;
                    break;
                default:
                    av = a.amount || 0;
                    bv = b.amount || 0;
            }
            if (av < bv) return sortDir;
            if (av > bv) return -sortDir;
            return 0;
        });
    }

    function formatDollars(val) {
        if (val == null || isNaN(val) || val === 0) return '--';
        const abs = Math.abs(val);
        if (abs >= 1e9) return '$' + (val / 1e9).toFixed(1) + 'B';
        if (abs >= 1e6) return '$' + (val / 1e6).toFixed(1) + 'M';
        if (abs >= 1e3) return '$' + (val / 1e3).toFixed(0) + 'K';
        return '$' + val.toLocaleString();
    }

    function formatDollarsExact(val) {
        if (val == null || isNaN(val) || val === 0) return 'Undisclosed';
        return '$' + val.toLocaleString();
    }

    function getSectors() {
        const sectors = new Set();
        rows.forEach(r => sectors.add(r.sector));
        return Array.from(sectors).sort();
    }

    function renderSummaryStats() {
        // Always compute from ALL rows (not filtered) so the totals are stable
        const allTotal = rows.reduce((sum, r) => sum + (r.amount || 0), 0);
        const allDecisions = rows.length;
        const allFlagged = rows.filter(r => r.flags.length > 0).length;
        const allSoleSource = rows.filter(r => r.decisionType === 'sole-source' || r.flags.some(f => f.type === 'sole-source')).length;
        const allInsiderTotal = rows
            .filter(r => r.connectionStrength === 'strong' || r.connectionStrength === 'very_strong' || r.connectionStrength === 'moderate')
            .reduce((sum, r) => sum + (r.amount || 0), 0);

        // Showing count for context when filtered
        const showingCount = filteredRows.length;
        const showingLabel = quickFilter ? `Showing ${showingCount} of ${allDecisions}` : `${allDecisions}`;

        const container = document.getElementById('ledger-summary');
        if (!container) return;

        container.innerHTML = `
            <div class="ledger-stat ledger-stat-clickable ${quickFilter === null ? 'ledger-stat-active' : ''}" data-quick="all" title="Show all decisions">
                <span class="ledger-stat-value">${formatDollars(allTotal)}</span>
                <span class="ledger-stat-label">Total</span>
            </div>
            <div class="ledger-stat ledger-stat-clickable ${quickFilter === null ? 'ledger-stat-active' : ''}" data-quick="all" title="Show all decisions">
                <span class="ledger-stat-value">${showingLabel}</span>
                <span class="ledger-stat-label">Decisions</span>
            </div>
            <div class="ledger-stat ledger-stat-warn ledger-stat-clickable ${quickFilter === 'flagged' ? 'ledger-stat-active' : ''}" data-quick="flagged" title="Show only AG/OPP/IC flagged decisions">
                <span class="ledger-stat-value">${allFlagged}</span>
                <span class="ledger-stat-label">Flagged</span>
            </div>
            <div class="ledger-stat ledger-stat-warn ledger-stat-clickable ${quickFilter === 'sole-source' ? 'ledger-stat-active' : ''}" data-quick="sole-source" title="Show only sole-source contracts">
                <span class="ledger-stat-value">${allSoleSource}</span>
                <span class="ledger-stat-label">Sole-Source</span>
            </div>
            <div class="ledger-stat ledger-stat-danger ledger-stat-clickable ${quickFilter === 'insider' ? 'ledger-stat-active' : ''}" data-quick="insider" title="Show decisions with insider political connections">
                <span class="ledger-stat-value">${formatDollars(allInsiderTotal)}</span>
                <span class="ledger-stat-label">Insider-Connected</span>
            </div>
        `;

        // Bind click handlers
        container.querySelectorAll('.ledger-stat-clickable').forEach(el => {
            el.addEventListener('click', function () {
                const target = this.dataset.quick;
                if (target === 'all' || quickFilter === target) {
                    // Clear quick filter
                    quickFilter = null;
                } else {
                    quickFilter = target;
                }
                applyFilters();
                renderSummaryStats();
                renderTable();
            });
        });
    }

    function renderFilterBar() {
        const container = document.getElementById('ledger-filters');
        if (!container) return;

        const sectors = getSectors();
        const sectorOptions = sectors.map(s =>
            `<option value="${s}" ${filters.sector === s ? 'selected' : ''}>${SECTOR_LABELS[s] || s}</option>`
        ).join('');

        container.innerHTML = `
            <div class="ledger-filter-group">
                <input type="text" id="ledger-search" class="ledger-search-input" placeholder="Search recipients, people, notes..." value="${filters.search}">
            </div>
            <div class="ledger-filter-group">
                <select id="ledger-sector-filter" class="ledger-select">
                    <option value="all">All Sectors</option>
                    ${sectorOptions}
                </select>
            </div>
            <div class="ledger-filter-group">
                <select id="ledger-type-filter" class="ledger-select">
                    <option value="all" ${filters.decisionType === 'all' ? 'selected' : ''}>All Types</option>
                    <option value="competitive-bid" ${filters.decisionType === 'competitive-bid' ? 'selected' : ''}>Competitive Bid</option>
                    <option value="sole-source" ${filters.decisionType === 'sole-source' ? 'selected' : ''}>Sole-Source</option>
                    <option value="ministerial-override" ${filters.decisionType === 'ministerial-override' ? 'selected' : ''}>Ministerial Override</option>
                    <option value="legislative" ${filters.decisionType === 'legislative' ? 'selected' : ''}>Legislative</option>
                    <option value="progressive-p3" ${filters.decisionType === 'progressive-p3' ? 'selected' : ''}>Progressive P3</option>
                </select>
            </div>
            <div class="ledger-filter-group">
                <select id="ledger-connection-filter" class="ledger-select">
                    <option value="all" ${filters.connectionStrength === 'all' ? 'selected' : ''}>All Connections</option>
                    <option value="strong" ${filters.connectionStrength === 'strong' ? 'selected' : ''}>Strong / Very Strong</option>
                    <option value="very_strong" ${filters.connectionStrength === 'very_strong' ? 'selected' : ''}>Very Strong Only</option>
                </select>
            </div>
            <div class="ledger-filter-group">
                <label class="ledger-checkbox-label">
                    <input type="checkbox" id="ledger-flagged-filter" ${filters.flaggedOnly ? 'checked' : ''}>
                    Flagged Only
                </label>
            </div>
            <div class="ledger-filter-group">
                <button id="ledger-export-btn" class="ledger-export-btn" title="Export CSV">Export CSV</button>
            </div>
        `;

        // Bind events
        document.getElementById('ledger-search').addEventListener('input', function () {
            filters.search = this.value;
            applyFilters();
            renderSummaryStats();
            renderTable();
        });

        document.getElementById('ledger-sector-filter').addEventListener('change', function () {
            filters.sector = this.value;
            applyFilters();
            renderSummaryStats();
            renderTable();
        });

        document.getElementById('ledger-type-filter').addEventListener('change', function () {
            filters.decisionType = this.value;
            applyFilters();
            renderSummaryStats();
            renderTable();
        });

        document.getElementById('ledger-connection-filter').addEventListener('change', function () {
            filters.connectionStrength = this.value;
            applyFilters();
            renderSummaryStats();
            renderTable();
        });

        document.getElementById('ledger-flagged-filter').addEventListener('change', function () {
            filters.flaggedOnly = this.checked;
            applyFilters();
            renderSummaryStats();
            renderTable();
        });

        document.getElementById('ledger-export-btn').addEventListener('click', exportCSV);
    }

    function renderTable() {
        const container = document.getElementById('ledger-table-wrap');
        if (!container) return;

        const sortIcon = function (col) {
            if (sortCol !== col) return '<span class="ledger-sort-icon"></span>';
            return sortDir === -1
                ? '<span class="ledger-sort-icon ledger-sort-desc"></span>'
                : '<span class="ledger-sort-icon ledger-sort-asc"></span>';
        };

        let html = `<table class="ledger-table">
            <thead>
                <tr>
                    <th class="ledger-th ledger-th-amount" data-col="amount">Amount ${sortIcon('amount')}</th>
                    <th class="ledger-th ledger-th-recipient" data-col="recipient">Recipient ${sortIcon('recipient')}</th>
                    <th class="ledger-th ledger-th-sector" data-col="sector">Sector ${sortIcon('sector')}</th>
                    <th class="ledger-th ledger-th-type" data-col="decisionType">Decision Type ${sortIcon('decisionType')}</th>
                    <th class="ledger-th ledger-th-maker" data-col="decisionMaker">Decision Maker ${sortIcon('decisionMaker')}</th>
                    <th class="ledger-th ledger-th-connected" data-col="connections">Connected To ${sortIcon('connections')}</th>
                    <th class="ledger-th ledger-th-flags" data-col="flags">Flags ${sortIcon('flags')}</th>
                    <th class="ledger-th ledger-th-source">Source</th>
                </tr>
            </thead>
            <tbody>`;

        if (filteredRows.length === 0) {
            html += `<tr><td colspan="8" class="ledger-empty">No matching spending decisions found.</td></tr>`;
        }

        filteredRows.forEach(row => {
            const amountClass = row.amount ? '' : 'ledger-undisclosed';

            // Connected people pills
            const peoplePills = row.connectedPeople.map(p => {
                const violationClass = p.integrity_violations ? 'ledger-pill-violation' : 'ledger-pill-insider';
                return `<span class="ledger-pill ${violationClass}" title="${escapeHtml(p.role || '')}">${escapeHtml(p.name)}</span>`;
            }).join('');

            // Connection strength badge
            const connBadge = row.connectionStrength !== 'none'
                ? `<span class="ledger-conn-badge ledger-conn-${row.connectionStrength}">${row.connectionStrength.replace('_', ' ')}</span>`
                : '';

            // Flags
            const flagsHtml = row.flags.map(f => {
                const fClass = f.type === 'ag' ? 'ledger-flag-ag'
                    : f.type === 'opp' ? 'ledger-flag-opp'
                    : f.type === 'integrity' ? 'ledger-flag-integrity'
                    : f.type === 'sole-source' ? 'ledger-flag-ss'
                    : 'ledger-flag-fraud';
                return `<span class="ledger-flag ${fClass}" title="${escapeHtml(f.title)}">${f.label}</span>`;
            }).join('');

            // Decision type display
            const typeDisplay = {
                'competitive-bid': 'Competitive',
                'sole-source': 'Sole-Source',
                'ministerial-override': 'Ministerial',
                'legislative': 'Legislative',
                'progressive-p3': 'Progressive P3',
            }[row.decisionType] || row.decisionType;

            const typeClass = row.decisionType === 'sole-source' ? 'ledger-type-ss'
                : row.decisionType === 'ministerial-override' ? 'ledger-type-minister'
                : row.decisionType === 'legislative' ? 'ledger-type-legislative'
                : '';

            // Source link
            const sourceHtml = row.sourceUrl
                ? `<a href="${escapeHtml(row.sourceUrl)}" target="_blank" rel="noopener" class="ledger-source-link" title="${escapeHtml(row.sourceUrl)}">Link</a>`
                : '<span class="ledger-no-source">--</span>';

            html += `<tr class="ledger-row" data-row-id="${row.id}">
                <td class="ledger-td ledger-td-amount ${amountClass}">${formatDollars(row.amount)}</td>
                <td class="ledger-td ledger-td-recipient" title="${escapeHtml(row.contract.name)}">${escapeHtml(row.recipient)}</td>
                <td class="ledger-td ledger-td-sector"><span class="ledger-sector-tag ledger-sector-${row.sector}">${escapeHtml(row.sectorLabel)}</span></td>
                <td class="ledger-td ledger-td-type ${typeClass}">${typeDisplay}</td>
                <td class="ledger-td ledger-td-maker">${escapeHtml(row.decisionMaker)}</td>
                <td class="ledger-td ledger-td-connected">${connBadge}${peoplePills}</td>
                <td class="ledger-td ledger-td-flags">${flagsHtml}</td>
                <td class="ledger-td ledger-td-source">${sourceHtml}</td>
            </tr>`;
        });

        html += `</tbody></table>`;
        container.innerHTML = html;

        // Bind sort headers
        container.querySelectorAll('.ledger-th[data-col]').forEach(th => {
            th.addEventListener('click', function () {
                const col = this.dataset.col;
                if (sortCol === col) {
                    sortDir = sortDir === -1 ? 1 : -1;
                } else {
                    sortCol = col;
                    sortDir = col === 'recipient' || col === 'sector' || col === 'decisionType' || col === 'decisionMaker' ? 1 : -1;
                }
                applyFilters();
                renderTable();
            });
        });

        // Bind row clicks
        container.querySelectorAll('.ledger-row').forEach(tr => {
            tr.addEventListener('click', function () {
                const rowId = this.dataset.rowId;
                const row = filteredRows.find(r => r.id === rowId);
                if (row) showRowDetail(row);
            });
        });
    }

    function showRowDetail(row) {
        let html = '';

        html += `<div class="info-section">
            <h4>Contract</h4>
            <div class="info-row"><span class="info-label">Name</span><span class="info-value">${escapeHtml(row.contract.name)}</span></div>
            <div class="info-row"><span class="info-label">Value</span><span class="info-value">${formatDollarsExact(row.amount)}</span></div>
            <div class="info-row"><span class="info-label">Status</span><span class="info-value">${escapeHtml(row.status)}</span></div>
            <div class="info-row"><span class="info-label">Sector</span><span class="info-value">${escapeHtml(row.sectorLabel)}</span></div>
            <div class="info-row"><span class="info-label">Decision Type</span><span class="info-value">${escapeHtml(row.decisionType)}</span></div>
            <div class="info-row"><span class="info-label">Decision Maker</span><span class="info-value">${escapeHtml(row.decisionMaker)}</span></div>
        </div>`;

        if (row.allCompanyNames.length > 0) {
            html += `<div class="info-section">
                <h4>Companies (${row.allCompanyNames.length})</h4>
                ${row.allCompanies.map(c => {
                    const connClass = c.connection_strength && c.connection_strength !== 'none'
                        ? `badge-${c.connection_strength}` : '';
                    const connLabel = c.connection_strength && c.connection_strength !== 'none'
                        ? `<span class="connection-badge ${connClass}">${c.connection_strength.replace('_', ' ')}</span>` : '';
                    const donLabel = c.donations_pc ? `<br><span style="color:var(--warning);font-size:0.75rem;">Donated $${c.donations_pc.toLocaleString()} to PCs</span>` : '';
                    const paLabel = c.public_accounts_total ? `<br><span style="color:var(--info);font-size:0.75rem;">Received ${App.formatCurrency(c.public_accounts_total)} (Public Accounts)</span>` : '';
                    const lobbyLabel = c.lobbyist_count ? `<br><span style="color:var(--accent);font-size:0.75rem;">${c.lobbyist_count} lobbyist registrations${c.lobbyist_firms && c.lobbyist_firms.length ? ' via ' + c.lobbyist_firms.slice(0, 2).join(', ') : ''}</span>` : '';
                    return `<div class="info-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="info-value" style="max-width:100%;text-align:left;">${escapeHtml(c.name)} ${connLabel}</span>
                        ${donLabel}${paLabel}${lobbyLabel}
                    </div>`;
                }).join('')}
            </div>`;
        }

        if (row.connectedPeople.length > 0) {
            html += `<div class="info-section">
                <h4>Political Connections</h4>
                ${row.connectedPeople.map(p => {
                    const viol = p.integrity_violations
                        ? '<span class="connection-badge badge-violation">Integrity Violations</span>' : '';
                    const donInfo = p.donations_pc_total ? `<br><span style="color:var(--warning);font-size:0.75rem;">Donated ${App.formatCurrency(p.donations_pc_total)} to PCs</span>` : '';
                    const sunInfo = p.sunshine_top_salary ? `<br><span style="color:var(--info);font-size:0.75rem;">Sunshine: ${p.sunshine_top_salary} at ${p.sunshine_top_employer || '?'} (${p.sunshine_top_year || '?'})</span>` : '';
                    const lobInfo = p.lobbyist_client_count ? `<br><span style="color:var(--accent);font-size:0.75rem;">${p.lobbyist_client_count}+ lobbyist clients</span>` : '';
                    return `<div class="info-row" style="flex-direction:column;align-items:flex-start;">
                        <span class="info-value" style="max-width:100%;text-align:left;">${escapeHtml(p.name)} ${viol}</span>
                        <span class="info-label" style="font-size:0.75rem;">${escapeHtml(p.role || '')}</span>
                        ${donInfo}${sunInfo}${lobInfo}
                    </div>`;
                }).join('')}
            </div>`;
        }

        if (row.flags.length > 0) {
            html += `<div class="info-section">
                <h4>Flags</h4>
                ${row.flags.map(f => `<div class="info-row"><span class="info-label">${escapeHtml(f.label)}</span><span class="info-value">${escapeHtml(f.title)}</span></div>`).join('')}
            </div>`;
        }

        if (row.notes) {
            html += `<div class="info-section">
                <h4>Notes</h4>
                <p style="font-size:0.8rem;color:var(--text-secondary);line-height:1.5;">${escapeHtml(row.notes)}</p>
            </div>`;
        }

        if (row.sourceUrl) {
            html += `<a href="${escapeHtml(row.sourceUrl)}" target="_blank" rel="noopener" class="info-link">View Source</a>`;
        }

        html += `<button class="info-link" style="margin-left:8px;background:var(--bg-tertiary);" onclick="App.switchToNetworkFor('${row.recipientId || ''}')">View in Network</button>`;

        App.setInfoPanel(row.contract.name, html);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function exportCSV() {
        const headers = ['Amount', 'Recipient', 'Contract Name', 'Sector', 'Decision Type', 'Decision Maker', 'Connected People', 'Flags', 'Connection Strength', 'PC Donations', 'Source URL', 'Notes'];
        const csvRows = [headers.join(',')];

        filteredRows.forEach(row => {
            const vals = [
                row.amount || '',
                '"' + (row.recipient || '').replace(/"/g, '""') + '"',
                '"' + (row.contract.name || '').replace(/"/g, '""') + '"',
                row.sectorLabel,
                row.decisionType,
                row.decisionMaker,
                '"' + row.connectedPeople.map(p => p.name).join('; ').replace(/"/g, '""') + '"',
                '"' + row.flags.map(f => f.label).join('; ').replace(/"/g, '""') + '"',
                row.connectionStrength,
                row.donationsPC || '',
                row.sourceUrl || '',
                '"' + (row.notes || '').replace(/"/g, '""') + '"',
            ];
            csvRows.push(vals.join(','));
        });

        const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'ontario-accountability-ledger.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function init(data) {
        allData = data;
        buildRows();
        applyFilters();
        renderFilterBar();
        renderSummaryStats();
        renderTable();
    }

    function render() {
        // Re-render on tab switch (in case window was resized)
        applyFilters();
        renderSummaryStats();
        renderTable();
    }

    return { init, render };
})();
