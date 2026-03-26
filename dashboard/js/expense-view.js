/**
 * Expense View — Zoomable D3 treemap for government spending.
 * Drill: Sectors -> Subcategories -> Contracts -> Companies
 */
const ExpenseView = (function () {
    let svg, tooltip, container;
    let data = null;
    let allData = null; // full app data ref
    let width = 0, height = 0;
    let zoomStack = []; // navigation stack
    let currentNode = null;

    const SECTOR_COLORS = {
        'health': '#e74c3c',
        'education': '#3498db',
        'transit-transportation': '#2ecc71',
        'children-social-services': '#9b59b6',
        'justice': '#e67e22',
        'interest-on-debt': '#95a5a6',
        'other-programs': '#6b7280',
    };

    function init(expenseData, fullData) {
        data = expenseData;
        allData = fullData;
        container = document.getElementById('spending-chart');
        tooltip = document.getElementById('tooltip');

        if (!data || !data.sectors || data.sectors.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">$</div><p>Expense data not available</p></div>';
            return;
        }

        svg = d3.select(container).append('svg');
        currentNode = buildTopLevel();
        renderTreemap();
        window.addEventListener('resize', debounce(onResize, 200));
    }

    function buildTopLevel() {
        return {
            name: 'Ontario Budget 2025-26',
            amount: data.total,
            level: 'root',
            children: data.sectors.map(s => ({
                ...s,
                level: 'sector',
            })),
        };
    }

    function renderTreemap(animate) {
        const rect = container.getBoundingClientRect();
        width = rect.width;
        height = rect.height;

        svg.attr('width', width).attr('height', height);
        svg.selectAll('*').remove();

        const root = d3.hierarchy(currentNode)
            .sum(d => d.children ? 0 : (d.amount || d.value || 0))
            .sort((a, b) => b.value - a.value);

        d3.treemap()
            .size([width, height])
            .paddingOuter(4)
            .paddingInner(2)
            .round(true)(root);

        const leaves = root.leaves();
        const parentTotal = currentNode.amount || d3.sum(leaves, d => d.value);

        const cell = svg.selectAll('g')
            .data(leaves)
            .join('g')
            .attr('class', 'treemap-cell')
            .attr('transform', d => `translate(${d.x0},${d.y0})`);

        if (animate) {
            cell.attr('opacity', 0).transition().duration(400).attr('opacity', 1);
        }

        cell.append('rect')
            .attr('width', d => Math.max(0, d.x1 - d.x0))
            .attr('height', d => Math.max(0, d.y1 - d.y0))
            .attr('fill', d => getCellColor(d.data))
            .attr('rx', 2);

        // Labels
        cell.each(function (d) {
            const w = d.x1 - d.x0;
            const h = d.y1 - d.y0;
            const g = d3.select(this);
            const amt = d.data.amount || d.data.value || d.value;
            const pct = (amt / parentTotal * 100).toFixed(1);

            if (w > 50 && h > 26) {
                g.append('text')
                    .attr('class', 'treemap-label')
                    .attr('x', 6).attr('y', 17)
                    .attr('font-size', w > 140 ? '0.85rem' : '0.72rem')
                    .text(truncate(d.data.name, Math.floor(w / 7)));
            }
            if (w > 50 && h > 40) {
                g.append('text')
                    .attr('class', 'treemap-amount')
                    .attr('x', 6).attr('y', 32)
                    .text(App.formatCurrency(amt));
            }
            if (w > 70 && h > 54) {
                g.append('text')
                    .attr('class', 'treemap-percent')
                    .attr('x', 6).attr('y', 46)
                    .text(`${pct}%`);
            }
            // Connection badge for companies
            if (d.data.connection_strength && d.data.connection_strength !== 'none' && w > 30 && h > 20) {
                const cs = d.data.connection_strength;
                const badgeColor = (cs === 'very_strong' || cs === 'strong' || cs === 'high') ? '#e74c3c'
                    : (cs === 'moderate' || cs === 'medium') ? '#f39c12' : '#f1c40f';
                g.append('circle')
                    .attr('cx', w - 12)
                    .attr('cy', 12)
                    .attr('r', 5)
                    .attr('fill', badgeColor)
                    .attr('stroke', 'rgba(0,0,0,0.3)')
                    .attr('stroke-width', 1);
                g.append('text')
                    .attr('class', 'connection-icon')
                    .attr('x', w - 12)
                    .attr('y', 15)
                    .attr('text-anchor', 'middle')
                    .attr('fill', 'white')
                    .text('\u26A0');
            }
        });

        // Interactions
        cell.on('mousemove', function (event, d) {
            const amt = d.data.amount || d.data.value || d.value;
            const pct = (amt / parentTotal * 100).toFixed(1);
            let detail = '';
            if (d.data.level === 'sector') {
                const subCount = (d.data.subcategories || []).length;
                detail = `<div class="tip-detail">${subCount} subcategories. Click to drill down.</div>`;
            } else if (d.data.level === 'contract') {
                detail = `<div class="tip-detail">${d.data.status || ''} ${d.data.companies_display || ''}</div>`;
            } else if (d.data.level === 'company') {
                const cs = d.data.connection_strength;
                if (cs && cs !== 'none') {
                    detail = `<div class="tip-detail">Political connection: <span class="badge-${cs}">${cs}</span>. Click for network view.</div>`;
                }
            }
            tooltip.innerHTML = `
                <div class="tip-title">${d.data.name}</div>
                <div class="tip-amount">${App.formatCurrency(amt)}</div>
                <div class="tip-percent">${pct}% of ${currentNode.name}</div>
                ${detail}
            `;
            tooltip.style.display = 'block';
            tooltip.style.left = (event.clientX + 14) + 'px';
            tooltip.style.top = (event.clientY - 10) + 'px';
        })
        .on('mouseleave', function () {
            tooltip.style.display = 'none';
        })
        .on('click', function (event, d) {
            handleClick(d.data);
        });
    }

    function handleClick(item) {
        // Show info panel
        showItemInfo(item);

        if (item.level === 'sector') {
            drillIntoSector(item);
        } else if (item.level === 'subcategory') {
            drillIntoSubcategory(item);
        } else if (item.level === 'contract') {
            drillIntoContract(item);
        } else if (item.level === 'company') {
            if (item.connection_strength && item.connection_strength !== 'none') {
                if (confirm(`View ${item.name} in the Network view?`)) {
                    App.switchToNetworkFor(item.id);
                }
            }
        }
    }

    function drillIntoSector(sector) {
        zoomStack.push(currentNode);
        const subcats = (sector.subcategories || []).map(sub => ({
            ...sub,
            level: 'subcategory',
            sectorId: sector.id,
            sectorColor: sector.color || SECTOR_COLORS[sector.id],
        }));

        currentNode = {
            name: sector.name,
            amount: sector.amount,
            level: 'sector-detail',
            color: sector.color,
            children: subcats.length > 0 ? subcats : [{ name: sector.name, amount: sector.amount, level: 'leaf', color: sector.color }],
        };
        updateBreadcrumb();
        renderTreemap(true);
    }

    function drillIntoSubcategory(sub) {
        zoomStack.push(currentNode);
        const contractIds = sub.contracts || [];
        let children = [];

        if (contractIds.length > 0) {
            children = contractIds.map(cid => {
                const contract = DataLoader.getContract(cid);
                if (contract) {
                    const companyNames = (contract.companies || []).map(compId => {
                        const comp = DataLoader.getCompany(compId);
                        return comp ? comp.name : compId;
                    }).join(', ');
                    return {
                        ...contract,
                        name: contract.name,
                        amount: contract.value,
                        level: 'contract',
                        companies_display: companyNames,
                        sectorColor: sub.sectorColor,
                    };
                }
                return { id: cid, name: cid, amount: 0, level: 'contract', sectorColor: sub.sectorColor };
            }).filter(c => c.amount > 0);
        }

        if (children.length === 0) {
            children = [{ name: sub.name, amount: sub.amount, level: 'leaf', sectorColor: sub.sectorColor }];
        }

        currentNode = {
            name: sub.name,
            amount: sub.amount,
            level: 'subcategory-detail',
            color: sub.sectorColor,
            children: children,
        };
        updateBreadcrumb();
        renderTreemap(true);
    }

    function drillIntoContract(contract) {
        const companyIds = contract.companies || [];
        if (companyIds.length === 0) return;

        zoomStack.push(currentNode);
        const children = companyIds.map(compId => {
            const comp = DataLoader.getCompany(compId);
            if (comp) {
                return {
                    ...comp,
                    name: comp.name,
                    amount: comp.total_gov_value || contract.value / companyIds.length,
                    level: 'company',
                    sectorColor: contract.sectorColor,
                };
            }
            return { id: compId, name: compId, amount: contract.value / companyIds.length, level: 'company', sectorColor: contract.sectorColor };
        });

        currentNode = {
            name: contract.name,
            amount: contract.value || contract.amount,
            level: 'contract-detail',
            children: children,
        };
        updateBreadcrumb();
        renderTreemap(true);
    }

    function goBack() {
        if (zoomStack.length > 0) {
            currentNode = zoomStack.pop();
            updateBreadcrumb();
            renderTreemap(true);
        }
    }

    function goToRoot() {
        zoomStack = [];
        currentNode = buildTopLevel();
        resetBreadcrumb();
        renderTreemap(true);
    }

    function updateBreadcrumb() {
        const bc = document.getElementById('spending-breadcrumb');
        let html = '<span class="crumb" onclick="ExpenseView.goToRoot()">All Sectors</span>';

        // Build from zoom stack + current
        const trail = [...zoomStack.slice(1), currentNode]; // skip root in stack
        trail.forEach((node, i) => {
            const isLast = i === trail.length - 1;
            html += '<span class="crumb-sep">&rsaquo;</span>';
            if (isLast) {
                html += `<span class="crumb active">${node.name}</span>`;
            } else {
                html += `<span class="crumb" onclick="ExpenseView.goBackTo(${i})">${node.name}</span>`;
            }
        });

        bc.innerHTML = html;
    }

    function goBackTo(index) {
        // Pop stack to index
        const target = index + 1; // +1 because we skip root
        while (zoomStack.length > target) {
            currentNode = zoomStack.pop();
        }
        updateBreadcrumb();
        renderTreemap(true);
    }

    function resetBreadcrumb() {
        const bc = document.getElementById('spending-breadcrumb');
        bc.innerHTML = '<span class="crumb active">All Sectors</span>';
    }

    function getCellColor(d) {
        if (d.color) return d.color;
        if (d.sectorColor) {
            // Slightly vary shade based on name
            const base = d3.color(d.sectorColor);
            if (base) {
                const variation = (hashStr(d.name || d.id || '') % 30 - 15) / 100;
                return base.brighter(variation).toString();
            }
            return d.sectorColor;
        }
        const sectorId = d.sectorId || d.sector;
        if (sectorId && SECTOR_COLORS[sectorId]) return SECTOR_COLORS[sectorId];
        return '#6b7280';
    }

    function showItemInfo(item) {
        let html = '';
        const amt = item.amount || item.value || 0;

        html += `<div class="info-row"><span class="info-label">Amount</span><span class="info-value">${App.formatCurrency(amt)}</span></div>`;

        if (item.level === 'sector') {
            const subCount = (item.subcategories || []).length;
            html += `<div class="info-row"><span class="info-label">Subcategories</span><span class="info-value">${subCount}</span></div>`;
            const pct = (amt / data.total * 100).toFixed(1);
            html += `<div class="info-row"><span class="info-label">% of Budget</span><span class="info-value">${pct}%</span></div>`;
        }

        if (item.level === 'contract') {
            if (item.status) html += `<div class="info-row"><span class="info-label">Status</span><span class="info-value">${item.status}</span></div>`;
            if (item.companies_display) html += `<div class="info-row"><span class="info-label">Companies</span><span class="info-value">${item.companies_display}</span></div>`;
            if (item.source_url) html += `<a class="info-link" href="${item.source_url}" target="_blank" rel="noopener">View Source</a>`;
        }

        if (item.level === 'company') {
            if (item.connection_strength && item.connection_strength !== 'none') {
                html += `<div class="info-row"><span class="info-label">Connection</span><span class="info-value"><span class="connection-badge badge-${item.connection_strength}">${item.connection_strength}</span></span></div>`;
            }
            if (item.donations_pc) {
                html += `<div class="info-row"><span class="info-label">PC Donations</span><span class="info-value">${App.formatCurrency(item.donations_pc)}</span></div>`;
            }
            if (item.total_gov_value) {
                html += `<div class="info-row"><span class="info-label">Total Gov Value</span><span class="info-value">${App.formatCurrency(item.total_gov_value)}</span></div>`;
            }
            html += `<button class="info-link" onclick="App.switchToNetworkFor('${item.id}')">View in Network</button>`;
        }

        App.setInfoPanel(item.name, html);
    }

    /**
     * Focus on a specific sector by ID (called from search).
     */
    function focusSector(sectorId) {
        if (!data || !data.sectors) return;
        goToRoot();
        const sector = data.sectors.find(s => s.id === sectorId);
        if (sector) {
            drillIntoSector({ ...sector, level: 'sector' });
        }
    }

    function hashStr(s) {
        let h = 0;
        for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
        return h;
    }

    function truncate(str, max) {
        if (!str) return '';
        return str.length > max ? str.slice(0, max - 1) + '\u2026' : str;
    }

    function debounce(fn, ms) {
        let t;
        return function () { clearTimeout(t); t = setTimeout(fn, ms); };
    }

    function onResize() {
        if (data) renderTreemap();
    }

    return { init, render: onResize, goBack, goToRoot, goBackTo, focusSector };
})();
