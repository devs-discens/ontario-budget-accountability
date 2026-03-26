/**
 * Flow View — Multi-layer Sankey diagram showing the full ecosystem of money flow:
 * Revenue Sources -> Government of Ontario -> Expense Sectors -> Subcategories -> Contracts -> Companies -> People
 *
 * Uses progressive disclosure: starts at Layers 1-2 (Revenue -> Sectors).
 * Click a sector to drill into subcategories/contracts.
 * Click a contract to see companies. Click a company to see political connections.
 */
const FlowView = (function () {
    let svg, gRoot, tooltip, container;
    let allData = null;
    let width = 0, height = 0;

    // Drill state
    const STATE_OVERVIEW = 'overview';           // Revenue -> Gov -> Sectors
    const STATE_SECTOR = 'sector';               // + Subcategories + Contracts
    const STATE_CONTRACT = 'contract';           // + Companies
    const STATE_COMPANY = 'company';             // + People

    let drillState = STATE_OVERVIEW;
    let selectedSector = null;
    let selectedContract = null;
    let selectedCompany = null;
    let showPolitical = false;

    // Color maps
    const SECTOR_COLORS = {
        'health': '#dc2626',
        'education': '#2563eb',
        'postsecondary': '#6366f1',
        'other-programs': '#6b7280',
        'children-social-services': '#7c3aed',
        'interest-on-debt': '#374151',
        'transit-transportation': '#059669',
        'justice': '#92400e',
    };
    const BORROWING_COLOR = '#e67e22';
    const REVENUE_COLOR = '#4fc3f7';
    const POLITICAL_COLOR = '#e74c3c';
    const GOV_COLOR = '#4fc3f7';

    function init(containerEl, data) {
        allData = data;
        container = containerEl;
        tooltip = document.getElementById('tooltip');

        if (!allData || !allData.revenue || !allData.expenses) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">&#8594;</div><p>Flow data not available</p></div>';
            return;
        }

        svg = d3.select(container).append('svg');
        gRoot = svg.append('g');

        // Bind political toggle
        const toggle = document.getElementById('flow-political-toggle');
        if (toggle) {
            toggle.addEventListener('change', function () {
                showPolitical = this.checked;
                render();
            });
        }

        window.addEventListener('resize', debounce(render, 200));
    }

    function render() {
        if (!allData || !allData.revenue || !allData.expenses) return;

        const rect = container.getBoundingClientRect();
        width = rect.width;
        height = rect.height;
        if (width < 100 || height < 100) return;

        svg.attr('width', width).attr('height', height);
        gRoot.selectAll('*').remove();

        // Remove old back buttons
        container.querySelectorAll('.flow-back-btn').forEach(el => el.remove());

        updateBreadcrumb();

        switch (drillState) {
            case STATE_OVERVIEW:
                renderOverview();
                break;
            case STATE_SECTOR:
                renderSectorDrill();
                break;
            case STATE_CONTRACT:
                renderContractDrill();
                break;
            case STATE_COMPANY:
                renderCompanyDrill();
                break;
        }
    }

    // ===== OVERVIEW: Revenue -> Government -> Sectors =====
    function renderOverview() {
        const revenue = allData.revenue;
        const expenses = allData.expenses;
        const nodes = [];
        const links = [];

        // Revenue sources
        revenue.sources.forEach(s => {
            nodes.push({
                id: 'rev-' + s.id,
                name: s.name,
                color: s.color || '#3498db',
                realAmount: s.amount,
                layer: 'revenue',
            });
        });

        // Borrowing (deficit)
        const deficit = expenses.total - revenue.total;
        if (deficit > 0) {
            nodes.push({
                id: 'borrowing',
                name: 'Borrowing (Deficit)',
                color: BORROWING_COLOR,
                realAmount: deficit,
                layer: 'borrowing',
            });
        }

        // Government node
        nodes.push({
            id: 'government',
            name: 'Government of Ontario',
            color: GOV_COLOR,
            realAmount: expenses.total,
            layer: 'government',
        });

        // Expense sectors
        expenses.sectors.forEach(s => {
            nodes.push({
                id: 'exp-' + s.id,
                name: s.name,
                color: s.color || '#6b7280',
                realAmount: s.amount,
                layer: 'sector',
                sectorId: s.id,
            });
        });

        // Links: revenue -> gov
        revenue.sources.forEach(s => {
            links.push({
                source: 'rev-' + s.id,
                target: 'government',
                value: s.amount / 1e6,
                realValue: s.amount,
                color: adjustAlpha(s.color || '#3498db', 0.5),
                linkType: 'revenue',
            });
        });

        // Borrowing -> gov
        if (deficit > 0) {
            links.push({
                source: 'borrowing',
                target: 'government',
                value: deficit / 1e6,
                realValue: deficit,
                color: BORROWING_COLOR,
                linkType: 'borrowing',
            });
        }

        // Gov -> sectors
        expenses.sectors.forEach(s => {
            links.push({
                source: 'government',
                target: 'exp-' + s.id,
                value: s.amount / 1e6,
                realValue: s.amount,
                color: s.color || '#6b7280',
                linkType: 'sector',
            });
        });

        // If political overlay is on, add political connection links at overview level
        if (showPolitical) {
            addPoliticalOverlayToOverview(nodes, links);
        }

        drawSankey(nodes, links, { clickSector: true });
    }

    function addPoliticalOverlayToOverview(nodes, links) {
        // Show companies with strong/very_strong connections linked to their sectors
        if (!allData.companies || !allData.companies.companies) return;
        if (!allData.connections || !allData.connections.connections) return;

        const addedCompanies = new Set();
        const addedPeople = new Set();

        allData.companies.companies.forEach(comp => {
            if (comp.connection_strength !== 'strong' && comp.connection_strength !== 'very_strong') return;
            if (!comp.contracts || comp.contracts.length === 0) return;

            // Find which sectors this company's contracts belong to
            const sectors = new Set();
            comp.contracts.forEach(cid => {
                const contract = DataLoader.getContract(cid);
                if (contract) {
                    // Find which expense sector has this contract
                    allData.expenses.sectors.forEach(s => {
                        if (s.subcategories) {
                            s.subcategories.forEach(sub => {
                                if (sub.contracts && sub.contracts.includes(cid)) {
                                    sectors.add(s.id);
                                }
                            });
                        }
                    });
                }
            });

            if (sectors.size === 0) return;

            // Add company node
            if (!addedCompanies.has(comp.id)) {
                nodes.push({
                    id: 'comp-' + comp.id,
                    name: comp.name,
                    color: POLITICAL_COLOR,
                    realAmount: comp.total_gov_value || 0,
                    layer: 'political-company',
                    companyData: comp,
                });
                addedCompanies.add(comp.id);
            }

            // Link from sector -> company
            sectors.forEach(sid => {
                const amount = comp.total_gov_value || 1000000;
                links.push({
                    source: 'exp-' + sid,
                    target: 'comp-' + comp.id,
                    value: Math.max(amount / 1e6, 1),
                    realValue: amount,
                    color: POLITICAL_COLOR,
                    linkType: 'political',
                    dashArray: '6,3',
                });
            });

            // Add lobbyist people
            if (comp.lobbyists) {
                comp.lobbyists.forEach(pid => {
                    const person = DataLoader.getPerson(pid);
                    if (!person) return;
                    if (!addedPeople.has(pid)) {
                        nodes.push({
                            id: 'person-' + pid,
                            name: person.name,
                            color: person.integrity_violations ? '#ff4444' : POLITICAL_COLOR,
                            realAmount: 0,
                            layer: 'political-person',
                            personData: person,
                        });
                        addedPeople.add(pid);
                    }
                    links.push({
                        source: 'comp-' + comp.id,
                        target: 'person-' + pid,
                        value: 1,
                        realValue: 0,
                        color: POLITICAL_COLOR,
                        linkType: 'political',
                        dashArray: '6,3',
                    });
                });
            }
        });
    }

    // ===== SECTOR DRILL: Sector -> Subcategories -> Contracts =====
    function renderSectorDrill() {
        if (!selectedSector) { drillState = STATE_OVERVIEW; renderOverview(); return; }

        const sector = allData.expenses.sectors.find(s => s.id === selectedSector);
        if (!sector) { drillState = STATE_OVERVIEW; renderOverview(); return; }

        const nodes = [];
        const links = [];

        // Sector node (left)
        nodes.push({
            id: 'sector-root',
            name: sector.name,
            color: sector.color || '#6b7280',
            realAmount: sector.amount,
            layer: 'sector-root',
        });

        // Subcategories
        const subs = sector.subcategories || [];
        subs.forEach(sub => {
            nodes.push({
                id: 'sub-' + sub.id,
                name: sub.name,
                color: lightenColor(sector.color || '#6b7280', 0.3),
                realAmount: sub.amount,
                layer: 'subcategory',
            });
            links.push({
                source: 'sector-root',
                target: 'sub-' + sub.id,
                value: sub.amount / 1e6,
                realValue: sub.amount,
                color: sector.color || '#6b7280',
                linkType: 'sector-sub',
            });

            // Contracts under this subcategory
            if (sub.contracts && sub.contracts.length > 0) {
                sub.contracts.forEach(cid => {
                    const contract = DataLoader.getContract(cid);
                    if (!contract) return;
                    const contractNodeId = 'contract-' + cid;
                    // Avoid duplicate contract nodes
                    if (!nodes.find(n => n.id === contractNodeId)) {
                        nodes.push({
                            id: contractNodeId,
                            name: contract.name,
                            color: '#4a90d9',
                            realAmount: contract.value || 0,
                            layer: 'contract',
                            contractId: cid,
                            contractData: contract,
                        });
                    }
                    const val = contract.value || sub.amount / Math.max(sub.contracts.length, 1);
                    links.push({
                        source: 'sub-' + sub.id,
                        target: contractNodeId,
                        value: Math.max(val / 1e6, 1),
                        realValue: val,
                        color: '#4a90d9',
                        linkType: 'sub-contract',
                    });
                });
            }
        });

        drawSankey(nodes, links, { clickContract: true });
    }

    // ===== CONTRACT DRILL: Contract -> Companies =====
    function renderContractDrill() {
        if (!selectedContract) { drillState = STATE_SECTOR; renderSectorDrill(); return; }

        const contract = DataLoader.getContract(selectedContract);
        if (!contract) { drillState = STATE_SECTOR; renderSectorDrill(); return; }

        const nodes = [];
        const links = [];

        // Find the sector and subcategory
        let parentSector = null;
        let parentSub = null;
        allData.expenses.sectors.forEach(s => {
            if (s.subcategories) {
                s.subcategories.forEach(sub => {
                    if (sub.contracts && sub.contracts.includes(selectedContract)) {
                        parentSector = s;
                        parentSub = sub;
                    }
                });
            }
        });

        // Sector node
        if (parentSector) {
            nodes.push({
                id: 'sector-root',
                name: parentSector.name,
                color: parentSector.color || '#6b7280',
                realAmount: parentSector.amount,
                layer: 'sector-root',
            });
        }

        // Subcategory
        if (parentSub) {
            nodes.push({
                id: 'sub-root',
                name: parentSub.name,
                color: parentSector ? lightenColor(parentSector.color || '#6b7280', 0.3) : '#6b7280',
                realAmount: parentSub.amount,
                layer: 'subcategory',
            });
            if (parentSector) {
                links.push({
                    source: 'sector-root',
                    target: 'sub-root',
                    value: parentSub.amount / 1e6,
                    realValue: parentSub.amount,
                    color: parentSector.color || '#6b7280',
                    linkType: 'sector-sub',
                });
            }
        }

        // Contract node
        nodes.push({
            id: 'contract-root',
            name: contract.name,
            color: '#4a90d9',
            realAmount: contract.value || 0,
            layer: 'contract',
            contractData: contract,
        });

        const contractValue = contract.value || (parentSub ? parentSub.amount : 1000000);
        links.push({
            source: parentSub ? 'sub-root' : 'sector-root',
            target: 'contract-root',
            value: Math.max(contractValue / 1e6, 1),
            realValue: contractValue,
            color: '#4a90d9',
            linkType: 'sub-contract',
        });

        // Companies
        const companyIds = contract.companies || [];
        const perCompanyValue = contractValue / Math.max(companyIds.length, 1);

        companyIds.forEach(cid => {
            const company = DataLoader.getCompany(cid);
            const compName = company ? company.name : cid;
            const isStrong = company && (company.connection_strength === 'strong' || company.connection_strength === 'very_strong');

            nodes.push({
                id: 'comp-' + cid,
                name: compName,
                color: isStrong ? POLITICAL_COLOR : '#34d399',
                realAmount: company ? (company.total_gov_value || perCompanyValue) : perCompanyValue,
                layer: 'company',
                companyId: cid,
                companyData: company,
                isStrong: isStrong,
            });
            links.push({
                source: 'contract-root',
                target: 'comp-' + cid,
                value: Math.max(perCompanyValue / 1e6, 1),
                realValue: perCompanyValue,
                color: isStrong ? POLITICAL_COLOR : '#34d399',
                linkType: isStrong ? 'political' : 'company',
            });

            // If political overlay enabled, show lobbyists
            if (showPolitical && company && company.lobbyists && company.lobbyists.length > 0) {
                addCompanyPoliticalLinks(company, nodes, links);
            }
        });

        drawSankey(nodes, links, { clickCompany: true });
    }

    // ===== COMPANY DRILL: Company -> Political connections =====
    function renderCompanyDrill() {
        if (!selectedCompany) { drillState = STATE_CONTRACT; renderContractDrill(); return; }

        const company = DataLoader.getCompany(selectedCompany);
        if (!company) { drillState = STATE_CONTRACT; renderContractDrill(); return; }

        const nodes = [];
        const links = [];

        // Find contracts for this company
        const contracts = DataLoader.getCompanyContracts(selectedCompany) || [];

        // Contracts as left nodes
        contracts.forEach(c => {
            nodes.push({
                id: 'contract-' + c.id,
                name: c.name,
                color: '#4a90d9',
                realAmount: c.value || 0,
                layer: 'contract',
            });
        });

        // Company node (center)
        const isStrong = company.connection_strength === 'strong' || company.connection_strength === 'very_strong';
        nodes.push({
            id: 'comp-root',
            name: company.name,
            color: isStrong ? POLITICAL_COLOR : '#34d399',
            realAmount: company.total_gov_value || 0,
            layer: 'company-root',
            companyData: company,
            isStrong: isStrong,
        });

        contracts.forEach(c => {
            const val = c.value || 1000000;
            links.push({
                source: 'contract-' + c.id,
                target: 'comp-root',
                value: Math.max(val / 1e6, 1),
                realValue: val,
                color: '#4a90d9',
                linkType: 'company',
            });
        });

        // If no contracts, still show the company
        if (contracts.length === 0) {
            // Add a stub node
            nodes.push({
                id: 'stub-source',
                name: 'Government Funding',
                color: GOV_COLOR,
                realAmount: company.total_gov_value || 0,
                layer: 'stub',
            });
            links.push({
                source: 'stub-source',
                target: 'comp-root',
                value: Math.max((company.total_gov_value || 1000000) / 1e6, 1),
                realValue: company.total_gov_value || 0,
                color: GOV_COLOR,
                linkType: 'company',
            });
        }

        // Political connections: lobbyists
        addCompanyPoliticalLinks(company, nodes, links, 'comp-root');

        // Also add connections from connections.json where company is the target
        const edges = DataLoader.getNodeEdges(selectedCompany) || [];
        edges.forEach(edge => {
            // Person -> company connections
            const personId = edge.from !== selectedCompany ? edge.from : edge.to;
            if (personId === selectedCompany) return; // self reference
            const person = DataLoader.getPerson(personId);
            if (!person) return;

            const personNodeId = 'person-' + personId;
            if (!nodes.find(n => n.id === personNodeId)) {
                nodes.push({
                    id: personNodeId,
                    name: person.name,
                    color: person.integrity_violations ? '#ff4444' : POLITICAL_COLOR,
                    realAmount: 0,
                    layer: 'person',
                    personData: person,
                });
            }
            if (!links.find(l => l.source === 'comp-root' && l.target === personNodeId)) {
                links.push({
                    source: 'comp-root',
                    target: personNodeId,
                    value: 1,
                    realValue: edge.amount || 0,
                    color: POLITICAL_COLOR,
                    linkType: 'political',
                    dashArray: '6,3',
                    evidence: edge.evidence,
                    connectionType: edge.type,
                });
            }
        });

        drawSankey(nodes, links, {});
    }

    function addCompanyPoliticalLinks(company, nodes, links, companyNodeId) {
        const cNodeId = companyNodeId || ('comp-' + company.id);
        const addedPeople = new Set(nodes.filter(n => n.layer === 'person').map(n => n.id));

        // Lobbyists listed on the company
        if (company.lobbyists) {
            company.lobbyists.forEach(pid => {
                const person = DataLoader.getPerson(pid);
                if (!person) return;
                const personNodeId = 'person-' + pid;
                if (!addedPeople.has(personNodeId)) {
                    nodes.push({
                        id: personNodeId,
                        name: person.name,
                        color: person.integrity_violations ? '#ff4444' : POLITICAL_COLOR,
                        realAmount: 0,
                        layer: 'person',
                        personData: person,
                    });
                    addedPeople.add(personNodeId);
                }
                if (!links.find(l => l.source === cNodeId && l.target === personNodeId)) {
                    links.push({
                        source: cNodeId,
                        target: personNodeId,
                        value: 1,
                        realValue: 0,
                        color: POLITICAL_COLOR,
                        linkType: 'political',
                        dashArray: '6,3',
                    });
                }
            });
        }

        // Connections from connections.json
        if (allData.connections && allData.connections.connections) {
            allData.connections.connections.forEach(edge => {
                if (edge.to !== company.id && edge.from !== company.id) return;
                const personId = edge.from !== company.id ? edge.from : edge.to;
                if (personId === company.id) return;
                const person = DataLoader.getPerson(personId);
                if (!person) return;
                const personNodeId = 'person-' + personId;
                if (!addedPeople.has(personNodeId)) {
                    nodes.push({
                        id: personNodeId,
                        name: person.name,
                        color: person.integrity_violations ? '#ff4444' : POLITICAL_COLOR,
                        realAmount: 0,
                        layer: 'person',
                        personData: person,
                    });
                    addedPeople.add(personNodeId);
                }
                if (!links.find(l => l.source === cNodeId && l.target === personNodeId)) {
                    links.push({
                        source: cNodeId,
                        target: personNodeId,
                        value: 1,
                        realValue: edge.amount || 0,
                        color: POLITICAL_COLOR,
                        linkType: 'political',
                        dashArray: '6,3',
                        evidence: edge.evidence,
                        connectionType: edge.type,
                    });
                }
            });
        }
    }

    // ===== DRAW SANKEY =====
    function drawSankey(nodesData, linksData, options) {
        if (nodesData.length === 0) return;

        const margin = { top: 24, right: 180, bottom: 24, left: 180 };
        const innerWidth = width - margin.left - margin.right;
        const innerHeight = height - margin.top - margin.bottom;
        if (innerWidth < 50 || innerHeight < 50) return;

        const g = gRoot.attr('transform', `translate(${margin.left},${margin.top})`);

        // Build sankey
        const sankey = d3.sankey()
            .nodeId(d => d.id)
            .nodeWidth(20)
            .nodePadding(Math.max(4, Math.min(14, innerHeight / nodesData.length)))
            .nodeAlign(d3.sankeyJustify)
            .extent([[0, 0], [innerWidth, innerHeight]]);

        let graph;
        try {
            graph = sankey({
                nodes: nodesData.map(d => ({ ...d })),
                links: linksData.map(d => ({ ...d })),
            });
        } catch (e) {
            console.warn('Sankey layout error:', e);
            g.append('text')
                .attr('x', innerWidth / 2)
                .attr('y', innerHeight / 2)
                .attr('text-anchor', 'middle')
                .attr('fill', '#ccc')
                .text('Unable to render this level. Try a different selection.');
            return;
        }

        // Draw links
        const linkSel = g.append('g')
            .attr('class', 'flow-links')
            .selectAll('path')
            .data(graph.links)
            .join('path')
            .attr('class', d => 'sankey-link' + (d.linkType === 'political' ? ' sankey-link-political' : ''))
            .attr('d', d3.sankeyLinkHorizontal())
            .attr('stroke', d => d.color || '#555')
            .attr('stroke-width', d => Math.max(1, d.width))
            .attr('stroke-dasharray', d => d.dashArray || null);

        linkSel.on('mousemove', function (event, d) {
            d3.select(this).attr('stroke-opacity', 0.6);
            let tipHtml = `<div class="tip-title">${d.source.name} &rarr; ${d.target.name}</div>`;
            if (d.realValue) {
                tipHtml += `<div class="tip-amount">${App.formatCurrency(d.realValue)}</div>`;
            }
            if (d.connectionType) {
                tipHtml += `<div class="tip-detail">Type: ${d.connectionType.replace(/_/g, ' ')}</div>`;
            }
            if (d.evidence) {
                tipHtml += `<div class="tip-detail">${truncate(d.evidence, 120)}</div>`;
            }
            showTooltip(event, tipHtml);
        })
        .on('mouseleave', function () {
            d3.select(this).attr('stroke-opacity', d => d.linkType === 'political' ? 0.4 : 0.25);
            hideTooltip();
        });

        // Political links get different default opacity
        linkSel.filter(d => d.linkType === 'political')
            .attr('stroke-opacity', 0.4);

        // Draw nodes
        const nodeSel = g.append('g')
            .selectAll('g')
            .data(graph.nodes)
            .join('g')
            .attr('class', 'sankey-node');

        // Determine node shape: circles for people, rectangles for everything else
        nodeSel.each(function (d) {
            const el = d3.select(this);
            if (d.layer === 'person' || d.layer === 'political-person') {
                // Circle for people
                const cx = (d.x0 + d.x1) / 2;
                const cy = (d.y0 + d.y1) / 2;
                const r = Math.max(6, Math.min(16, (d.y1 - d.y0) / 2));
                el.append('circle')
                    .attr('cx', cx)
                    .attr('cy', cy)
                    .attr('r', r)
                    .attr('fill', d.color)
                    .attr('stroke', d.personData && d.personData.integrity_violations ? '#ff4444' : 'none')
                    .attr('stroke-width', d.personData && d.personData.integrity_violations ? 3 : 0);
            } else {
                // Rectangle
                el.append('rect')
                    .attr('x', d.x0)
                    .attr('y', d.y0)
                    .attr('height', Math.max(1, d.y1 - d.y0))
                    .attr('width', d.x1 - d.x0)
                    .attr('fill', d.color || '#4a4a6a')
                    .attr('rx', d.layer === 'government' ? 4 : 2)
                    .attr('stroke', d.isStrong ? POLITICAL_COLOR : 'none')
                    .attr('stroke-width', d.isStrong ? 2 : 0);
            }
        });

        // Node labels
        nodeSel.append('text')
            .attr('x', d => d.x0 < innerWidth / 2 ? d.x0 - 8 : d.x1 + 8)
            .attr('y', d => (d.y0 + d.y1) / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', d => d.x0 < innerWidth / 2 ? 'end' : 'start')
            .text(d => truncate(d.name, 32))
            .attr('fill', '#ccc')
            .attr('font-size', nodesData.length > 30 ? '0.68rem' : '0.78rem');

        // Amount labels
        nodeSel.append('text')
            .attr('x', d => d.x0 < innerWidth / 2 ? d.x0 - 8 : d.x1 + 8)
            .attr('y', d => (d.y0 + d.y1) / 2 + (nodesData.length > 30 ? 11 : 14))
            .attr('dy', '0.35em')
            .attr('text-anchor', d => d.x0 < innerWidth / 2 ? 'end' : 'start')
            .text(d => d.realAmount ? App.formatCurrency(d.realAmount) : '')
            .attr('fill', '#888')
            .attr('font-size', nodesData.length > 30 ? '0.6rem' : '0.68rem');

        // Node interactions
        nodeSel.style('cursor', d => {
            if (options.clickSector && d.layer === 'sector') return 'pointer';
            if (options.clickContract && d.layer === 'contract') return 'pointer';
            if (options.clickCompany && d.layer === 'company') return 'pointer';
            return 'default';
        });

        nodeSel.on('click', function (event, d) {
            if (options.clickSector && d.layer === 'sector' && d.sectorId) {
                drillIntoSector(d.sectorId);
            } else if (options.clickContract && d.layer === 'contract' && d.contractId) {
                drillIntoContract(d.contractId);
            } else if (options.clickCompany && d.layer === 'company' && d.companyId) {
                drillIntoCompany(d.companyId);
            }

            // Show info panel for all nodes
            showNodeInfo(d);
        });

        nodeSel.on('mousemove', function (event, d) {
            let tipHtml = `<div class="tip-title">${d.name}</div>`;
            if (d.realAmount) {
                tipHtml += `<div class="tip-amount">${App.formatCurrency(d.realAmount)}</div>`;
            }
            if (d.layer === 'sector') {
                tipHtml += `<div class="tip-detail">Click to drill into subcategories</div>`;
            } else if (d.layer === 'contract') {
                tipHtml += `<div class="tip-detail">Click to see companies</div>`;
            } else if (d.layer === 'company') {
                tipHtml += `<div class="tip-detail">Click to see connections</div>`;
            }
            if (d.personData) {
                tipHtml += `<div class="tip-detail">${d.personData.role}</div>`;
                if (d.personData.integrity_violations) {
                    tipHtml += `<div class="tip-detail" style="color:#ff4444">Integrity violations</div>`;
                }
            }
            if (d.companyData && d.companyData.connection_strength && d.companyData.connection_strength !== 'none') {
                tipHtml += `<div class="tip-detail">Political connection: ${d.companyData.connection_strength}</div>`;
            }
            showTooltip(event, tipHtml);
        })
        .on('mouseleave', function () {
            hideTooltip();
        });

        // Add back button for drilled states
        if (drillState !== STATE_OVERVIEW) {
            addBackButton();
        }
    }

    // ===== DRILL FUNCTIONS =====
    function drillIntoSector(sectorId) {
        selectedSector = sectorId;
        drillState = STATE_SECTOR;
        render();
    }

    function drillIntoContract(contractId) {
        selectedContract = contractId;
        drillState = STATE_CONTRACT;
        render();
    }

    function drillIntoCompany(companyId) {
        selectedCompany = companyId;
        drillState = STATE_COMPANY;
        render();
    }

    function goBack() {
        switch (drillState) {
            case STATE_COMPANY:
                drillState = STATE_CONTRACT;
                selectedCompany = null;
                break;
            case STATE_CONTRACT:
                drillState = STATE_SECTOR;
                selectedContract = null;
                break;
            case STATE_SECTOR:
                drillState = STATE_OVERVIEW;
                selectedSector = null;
                break;
        }
        render();
    }

    function goToOverview() {
        drillState = STATE_OVERVIEW;
        selectedSector = null;
        selectedContract = null;
        selectedCompany = null;
        render();
    }

    // ===== BREADCRUMB =====
    function updateBreadcrumb() {
        const bc = document.getElementById('flow-breadcrumb');
        if (!bc) return;

        const crumbs = [];
        crumbs.push({ label: 'Revenue \u2192 Sectors', action: goToOverview, active: drillState === STATE_OVERVIEW });

        if (drillState !== STATE_OVERVIEW && selectedSector) {
            const sector = allData.expenses.sectors.find(s => s.id === selectedSector);
            crumbs.push({
                label: sector ? sector.name : selectedSector,
                action: () => { drillState = STATE_SECTOR; selectedContract = null; selectedCompany = null; render(); },
                active: drillState === STATE_SECTOR,
            });
        }

        if ((drillState === STATE_CONTRACT || drillState === STATE_COMPANY) && selectedContract) {
            const contract = DataLoader.getContract(selectedContract);
            crumbs.push({
                label: contract ? truncate(contract.name, 28) : selectedContract,
                action: () => { drillState = STATE_CONTRACT; selectedCompany = null; render(); },
                active: drillState === STATE_CONTRACT,
            });
        }

        if (drillState === STATE_COMPANY && selectedCompany) {
            const company = DataLoader.getCompany(selectedCompany);
            crumbs.push({
                label: company ? company.name : selectedCompany,
                action: null,
                active: true,
            });
        }

        bc.innerHTML = '';
        crumbs.forEach((c, i) => {
            if (i > 0) {
                const sep = document.createElement('span');
                sep.className = 'crumb-sep';
                sep.textContent = '\u203A';
                bc.appendChild(sep);
            }
            const span = document.createElement('span');
            span.className = 'crumb' + (c.active ? ' active' : '');
            span.textContent = c.label;
            if (c.action && !c.active) {
                span.addEventListener('click', c.action);
            }
            bc.appendChild(span);
        });
    }

    // ===== BACK BUTTON =====
    function addBackButton() {
        const btn = document.createElement('button');
        btn.className = 'flow-back-btn';
        btn.innerHTML = '\u2190 Back';
        btn.addEventListener('click', goBack);
        container.appendChild(btn);
    }

    // ===== INFO PANEL =====
    function showNodeInfo(d) {
        let title = d.name;
        let body = '';

        if (d.realAmount) {
            body += `<div class="info-row"><span class="info-label">Amount</span><span class="info-value">${App.formatCurrency(d.realAmount)}</span></div>`;
        }

        if (d.layer === 'revenue') {
            const pct = (d.realAmount / allData.revenue.total * 100).toFixed(1);
            body += `<div class="info-row"><span class="info-label">% of Revenue</span><span class="info-value">${pct}%</span></div>`;
        }

        if (d.layer === 'sector' && d.sectorId) {
            const sector = allData.expenses.sectors.find(s => s.id === d.sectorId);
            if (sector) {
                const pct = (sector.amount / allData.expenses.total * 100).toFixed(1);
                body += `<div class="info-row"><span class="info-label">% of Spending</span><span class="info-value">${pct}%</span></div>`;
                if (sector.subcategories) {
                    body += `<div class="info-row"><span class="info-label">Subcategories</span><span class="info-value">${sector.subcategories.length}</span></div>`;
                }
                if (sector.notes) {
                    body += `<div class="info-section"><h4>Notes</h4><p style="font-size:0.78rem;color:var(--text-secondary)">${sector.notes}</p></div>`;
                }
                body += `<button class="info-link" onclick="FlowView.drillIntoSector('${d.sectorId}')">Drill into subcategories</button>`;
            }
        }

        if (d.contractData) {
            const c = d.contractData;
            body += `<div class="info-row"><span class="info-label">Status</span><span class="info-value">${c.status || 'N/A'}</span></div>`;
            body += `<div class="info-row"><span class="info-label">Sector</span><span class="info-value">${c.sector || 'N/A'}</span></div>`;
            if (c.companies && c.companies.length > 0) {
                body += `<div class="info-row"><span class="info-label">Companies</span><span class="info-value">${c.companies.length}</span></div>`;
            }
            if (c.notes) {
                body += `<div class="info-section"><h4>Notes</h4><p style="font-size:0.78rem;color:var(--text-secondary)">${c.notes}</p></div>`;
            }
            if (c.source_url) {
                body += `<div class="info-section"><a href="${c.source_url}" target="_blank" rel="noopener" class="info-link">Source</a></div>`;
            }
        }

        if (d.companyData) {
            const comp = d.companyData;
            if (comp.connection_strength && comp.connection_strength !== 'none') {
                body += `<div class="info-row"><span class="info-label">Political Connection</span><span class="info-value"><span class="connection-badge badge-${comp.connection_strength}">${comp.connection_strength}</span></span></div>`;
            }
            if (comp.donations_pc) {
                body += `<div class="info-row"><span class="info-label">PC Donations</span><span class="info-value">${App.formatCurrency(comp.donations_pc)}</span></div>`;
            }
            if (comp.lobbyists && comp.lobbyists.length > 0) {
                body += `<div class="info-row"><span class="info-label">Lobbyists</span><span class="info-value">${comp.lobbyists.length}</span></div>`;
            }
            if (comp.notes) {
                body += `<div class="info-section"><h4>Notes</h4><p style="font-size:0.78rem;color:var(--text-secondary)">${comp.notes}</p></div>`;
            }
            body += `<button class="info-link" onclick="App.switchToNetworkFor('${comp.id}')">View in Network</button>`;
        }

        if (d.personData) {
            const p = d.personData;
            body += `<div class="info-row"><span class="info-label">Role</span><span class="info-value" style="font-size:0.75rem">${p.role}</span></div>`;
            if (p.firm) {
                body += `<div class="info-row"><span class="info-label">Firm</span><span class="info-value">${p.firm}</span></div>`;
            }
            body += `<div class="info-row"><span class="info-label">Type</span><span class="info-value">${p.type}</span></div>`;
            if (p.integrity_violations) {
                body += `<div class="info-row"><span class="info-label">Integrity</span><span class="info-value"><span class="connection-badge badge-violation">Violations</span></span></div>`;
            }
            body += `<button class="info-link" onclick="App.switchToNetworkFor('${p.id}')">View in Network</button>`;
        }

        if (d.layer === 'borrowing') {
            body += `<div class="info-section"><h4>About</h4><p style="font-size:0.78rem;color:var(--text-secondary)">The deficit of ${App.formatCurrency(d.realAmount)} represents the gap between revenue (${App.formatCurrency(allData.revenue.total)}) and spending (${App.formatCurrency(allData.expenses.total)}), financed through borrowing.</p></div>`;
        }

        if (d.layer === 'government') {
            body += `<div class="info-section"><h4>About</h4><p style="font-size:0.78rem;color:var(--text-secondary)">Total government spending for 2025-26. Revenue (${App.formatCurrency(allData.revenue.total)}) plus borrowing (${App.formatCurrency(allData.expenses.total - allData.revenue.total)}) = ${App.formatCurrency(allData.expenses.total)}.</p></div>`;
        }

        App.setInfoPanel(title, body);
    }

    // ===== UTILITIES =====
    function showTooltip(event, html) {
        tooltip.innerHTML = html;
        tooltip.style.display = 'block';
        tooltip.style.left = (event.clientX + 14) + 'px';
        tooltip.style.top = (event.clientY - 10) + 'px';
    }

    function hideTooltip() {
        tooltip.style.display = 'none';
    }

    function truncate(str, max) {
        if (!str) return '';
        return str.length > max ? str.slice(0, max - 1) + '\u2026' : str;
    }

    function adjustAlpha(hex, alpha) {
        // Returns the hex color; actual opacity is handled by stroke-opacity
        return hex;
    }

    function lightenColor(hex, amount) {
        // Lighten a hex color
        let r = parseInt(hex.slice(1, 3), 16);
        let g = parseInt(hex.slice(3, 5), 16);
        let b = parseInt(hex.slice(5, 7), 16);
        r = Math.min(255, Math.round(r + (255 - r) * amount));
        g = Math.min(255, Math.round(g + (255 - g) * amount));
        b = Math.min(255, Math.round(b + (255 - b) * amount));
        return '#' + [r, g, b].map(c => c.toString(16).padStart(2, '0')).join('');
    }

    function debounce(fn, ms) {
        let t;
        return function () { clearTimeout(t); t = setTimeout(fn, ms); };
    }

    function onResize() {
        if (allData && allData.revenue && allData.expenses) render();
    }

    return {
        init,
        render: onResize,
        drillIntoSector,
        drillIntoContract,
        drillIntoCompany,
    };
})();
