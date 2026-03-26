/**
 * Revenue View — D3 treemap showing revenue sources.
 */
const RevenueView = (function () {
    let svg, tooltip, container;
    let data = null;
    let currentRoot = null;
    let width = 0, height = 0;

    function init(revenueData) {
        data = revenueData;
        container = document.getElementById('revenue-chart');
        tooltip = document.getElementById('tooltip');

        if (!data || !data.sources || data.sources.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">$</div><p>Revenue data not available</p></div>';
            return;
        }

        // Build hierarchy
        const hierarchy = {
            name: 'Revenue',
            amount: data.total,
            children: data.sources.map(s => ({
                ...s,
                children: s.subcategories && s.subcategories.length > 0
                    ? s.subcategories
                    : undefined,
            })),
        };

        currentRoot = hierarchy;

        svg = d3.select(container).append('svg');
        render();
        window.addEventListener('resize', debounce(render, 200));
    }

    function render(zoomTo) {
        const rect = container.getBoundingClientRect();
        width = rect.width;
        height = rect.height;

        svg.attr('width', width).attr('height', height);
        svg.selectAll('*').remove();

        const target = zoomTo || currentRoot;

        const root = d3.hierarchy(target)
            .sum(d => d.children ? 0 : (d.amount || 0))
            .sort((a, b) => b.value - a.value);

        d3.treemap()
            .size([width, height])
            .paddingOuter(3)
            .paddingInner(2)
            .round(true)(root);

        const leaves = root.leaves();
        const parentTotal = target.amount || d3.sum(leaves, d => d.value);

        const cell = svg.selectAll('g')
            .data(leaves)
            .join('g')
            .attr('class', 'treemap-cell')
            .attr('transform', d => `translate(${d.x0},${d.y0})`);

        cell.append('rect')
            .attr('width', d => Math.max(0, d.x1 - d.x0))
            .attr('height', d => Math.max(0, d.y1 - d.y0))
            .attr('fill', d => d.data.color || getRevenueColor(d.data))
            .attr('rx', 2);

        // Labels
        cell.each(function (d) {
            const w = d.x1 - d.x0;
            const h = d.y1 - d.y0;
            const g = d3.select(this);

            if (w > 60 && h > 30) {
                g.append('text')
                    .attr('class', 'treemap-label')
                    .attr('x', 6)
                    .attr('y', 18)
                    .attr('font-size', w > 150 ? '0.85rem' : '0.72rem')
                    .text(truncate(d.data.name, Math.floor(w / 7)));
            }
            if (w > 60 && h > 46) {
                g.append('text')
                    .attr('class', 'treemap-amount')
                    .attr('x', 6)
                    .attr('y', 34)
                    .text(App.formatCurrency(d.data.amount || d.value));
            }
            if (w > 80 && h > 58) {
                const pct = ((d.data.amount || d.value) / parentTotal * 100).toFixed(1);
                g.append('text')
                    .attr('class', 'treemap-percent')
                    .attr('x', 6)
                    .attr('y', 48)
                    .text(`${pct}% of total`);
            }
        });

        // Interactions
        cell.on('mousemove', function (event, d) {
            const pct = ((d.data.amount || d.value) / parentTotal * 100).toFixed(1);
            tooltip.innerHTML = `
                <div class="tip-title">${d.data.name}</div>
                <div class="tip-amount">${App.formatCurrency(d.data.amount || d.value)}</div>
                <div class="tip-percent">${pct}% of total revenue</div>
            `;
            tooltip.style.display = 'block';
            tooltip.style.left = (event.clientX + 14) + 'px';
            tooltip.style.top = (event.clientY - 10) + 'px';
        })
        .on('mouseleave', function () {
            tooltip.style.display = 'none';
        })
        .on('click', function (event, d) {
            showInfoPanel('revenue', d.data, parentTotal);
            // Zoom into subcategories if available
            if (d.data.subcategories && d.data.subcategories.length > 0) {
                zoomInto(d.data);
            }
        });
    }

    function zoomInto(node) {
        currentRoot = {
            name: node.name,
            amount: node.amount,
            children: node.subcategories || [],
        };
        updateBreadcrumb(node.name);
        render();
    }

    function zoomOut() {
        currentRoot = {
            name: 'Revenue',
            amount: data.total,
            children: data.sources.map(s => ({
                ...s,
                children: s.subcategories && s.subcategories.length > 0
                    ? s.subcategories
                    : undefined,
            })),
        };
        resetBreadcrumb();
        render();
    }

    function updateBreadcrumb(name) {
        const bc = document.getElementById('revenue-breadcrumb');
        bc.innerHTML = `
            <span class="crumb" onclick="RevenueView.zoomOut()">All Revenue Sources</span>
            <span class="crumb-sep">&rsaquo;</span>
            <span class="crumb active">${name}</span>
        `;
    }

    function resetBreadcrumb() {
        const bc = document.getElementById('revenue-breadcrumb');
        bc.innerHTML = '<span class="crumb active">All Revenue Sources</span>';
    }

    function showInfoPanel(type, item, parentTotal) {
        const pct = ((item.amount) / parentTotal * 100).toFixed(1);
        const html = `
            <div class="info-row"><span class="info-label">Name</span><span class="info-value">${item.name}</span></div>
            <div class="info-row"><span class="info-label">Amount</span><span class="info-value">${App.formatCurrency(item.amount)}</span></div>
            <div class="info-row"><span class="info-label">% of Total</span><span class="info-value">${pct}%</span></div>
        `;
        App.setInfoPanel(item.name, html);
    }

    function getRevenueColor(d) {
        // Fallback color scheme
        const colors = ['#2563eb', '#7c3aed', '#dc2626', '#059669', '#6b7280', '#d97706', '#9ca3af', '#0891b2', '#be185d', '#ea580c'];
        return d.color || colors[Math.abs(hashStr(d.name || '')) % colors.length];
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
        return function () {
            clearTimeout(t);
            t = setTimeout(fn, ms);
        };
    }

    function onResize() {
        if (data) render();
    }

    return { init, render: onResize, zoomOut };
})();
