/**
 * Network View — vis.js force-directed graph of political connections.
 */
const NetworkView = (function () {
    let network = null;
    let nodesDataset = null;
    let edgesDataset = null;
    let allNodes = [];
    let allEdges = [];
    let container = null;
    let tooltip = null;
    let fullData = null;
    let initialized = false;

    const NODE_SHAPES = {
        person: 'dot',
        company: 'square',
        political: 'diamond',
        fund: 'hexagon',
        party: 'diamond',
        government: 'triangle',
    };

    const EDGE_COLORS = {
        lobbies_for: { color: '#e67e22', dashes: [8, 4] },
        donated: { color: '#2ecc71', dashes: false },
        received_contract: { color: '#3498db', dashes: false },
        appointed_by: { color: '#95a5a6', dashes: [4, 4] },
        worked_for: { color: '#95a5a6', dashes: [4, 4] },
        hired: { color: '#9b59b6', dashes: [4, 4] },
    };

    function init(data) {
        fullData = data;
        container = document.getElementById('network-chart');
        tooltip = document.getElementById('tooltip');

        const hasPeople = data.people && data.people.people && data.people.people.length > 0;
        const hasCompanies = data.companies && data.companies.companies && data.companies.companies.length > 0;
        const connEdges = data.connections && (data.connections.edges || data.connections.connections);
        const hasConnections = connEdges && connEdges.length > 0;

        if (!hasPeople && !hasCompanies && !hasConnections) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">&#9741;</div><p>Network data not yet available</p><p style="font-size:0.78rem;color:#6b6b80;">Connections data files (companies.json, people.json, connections.json) are being prepared.</p></div>';
            return;
        }

        buildGraphData(data);
        createNetwork();
        bindFilters();
        initialized = true;
    }

    function buildGraphData(data) {
        allNodes = [];
        allEdges = [];
        const nodeIds = new Set();

        // Add people
        if (data.people && data.people.people) {
            data.people.people.forEach(p => {
                if (nodeIds.has(p.id)) return;
                nodeIds.add(p.id);

                let borderColor = '#555';
                let bgColor = '#444';
                if (p.integrity_violations) {
                    borderColor = '#e74c3c';
                    bgColor = '#5a2020';
                } else if (p.type === 'insider' || p.type === 'lobbyist-insider') {
                    borderColor = '#e67e22';
                    bgColor = '#4a3020';
                }

                allNodes.push({
                    id: p.id,
                    label: p.name,
                    shape: 'dot',
                    size: 14,
                    color: {
                        background: bgColor,
                        border: borderColor,
                        highlight: { background: '#555', border: borderColor },
                    },
                    borderWidth: p.integrity_violations ? 3 : 2,
                    font: { color: '#ccc', size: 11 },
                    title: `${p.name}\n${p.role || ''}\n${p.firm || ''}` +
                        (p.donations_pc_total ? `\nPC donations: ${App.formatCurrency(p.donations_pc_total)}` : '') +
                        (p.lobbyist_client_count ? `\nLobbyist clients: ${p.lobbyist_client_count}+` : '') +
                        (p.sunshine_top_salary ? `\nSunshine: ${p.sunshine_top_salary} (${p.sunshine_top_employer}, ${p.sunshine_top_year})` : ''),
                    entityType: 'person',
                    entityData: p,
                });
            });
        }

        // Add companies — only those with political connections (strength !== 'none')
        // or that appear in at least one connection edge
        const allConnEdges = data.connections && (data.connections.edges || data.connections.connections) || [];
        if (data.companies && data.companies.companies) {
            data.companies.companies.forEach(c => {
                if (nodeIds.has(c.id)) return;

                // Skip companies with no political connections
                const hasConnections = c.connection_strength && c.connection_strength !== 'none';
                const hasEdges = allConnEdges.some(e => e.from === c.id || e.to === c.id);
                const hasLobbyists = c.lobbyists && c.lobbyists.length > 0;
                if (!hasConnections && !hasEdges && !hasLobbyists) return;

                nodeIds.add(c.id);

                const val = c.total_gov_value || 0;
                const size = Math.max(12, Math.min(40, 10 + Math.sqrt(val / 1e8) * 3));

                let bgColor = '#3a3a55';
                let borderColor = '#666';
                if (c.connection_strength === 'very_strong') { bgColor = '#6a1515'; borderColor = '#ff4444'; }
                else if (c.connection_strength === 'strong' || c.connection_strength === 'high') { bgColor = '#5a2020'; borderColor = '#e74c3c'; }
                else if (c.connection_strength === 'moderate' || c.connection_strength === 'medium') { bgColor = '#4a3520'; borderColor = '#f39c12'; }
                else if (c.connection_strength === 'weak' || c.connection_strength === 'low') { bgColor = '#3a3a20'; borderColor = '#f1c40f'; }

                allNodes.push({
                    id: c.id,
                    label: c.name,
                    shape: 'square',
                    size: size,
                    color: {
                        background: bgColor,
                        border: borderColor,
                        highlight: { background: '#555', border: borderColor },
                    },
                    borderWidth: 2,
                    font: { color: '#ccc', size: 11 },
                    title: `${c.name}\nGov value: ${App.formatCurrency(val)}` +
                        (c.public_accounts_total ? `\nPublic Accounts: ${App.formatCurrency(c.public_accounts_total)}` : '') +
                        (c.lobbyist_count ? `\nLobbyist registrations: ${c.lobbyist_count}` : '') +
                        (c.donations_pc ? `\nPC donations: ${App.formatCurrency(c.donations_pc)}` : ''),
                    entityType: 'company',
                    entityData: c,
                    govValue: val,
                });
            });
        }

        // Add connections/edges + any implicit political entity nodes
        const edgeList = data.connections && (data.connections.edges || data.connections.connections);
        if (edgeList) {
            edgeList.forEach((e, i) => {
                // Ensure from/to nodes exist; create placeholder political entities if not
                [e.from, e.to].forEach(nid => {
                    if (!nodeIds.has(nid)) {
                        nodeIds.add(nid);
                        const isPolitical = /party|ontario-proud|pc-|liberal|ndp|green/i.test(nid);
                        const isFund = /fund|greenbelt|sdf/i.test(nid);
                        allNodes.push({
                            id: nid,
                            label: nid.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                            shape: isPolitical ? 'diamond' : (isFund ? 'hexagon' : 'dot'),
                            size: isPolitical ? 20 : (isFund ? 18 : 12),
                            color: {
                                background: isPolitical ? '#1a3a6e' : (isFund ? '#2a4a2a' : '#3a3a55'),
                                border: isPolitical ? '#3498db' : (isFund ? '#2ecc71' : '#666'),
                                highlight: { background: '#555', border: '#aaa' },
                            },
                            borderWidth: 2,
                            font: { color: '#ccc', size: 11 },
                            entityType: isPolitical ? 'political' : (isFund ? 'fund' : 'unknown'),
                            entityData: { id: nid, name: nid },
                        });
                    }
                });

                const edgeStyle = EDGE_COLORS[e.type] || { color: '#666', dashes: false };
                const edgeWidth = e.type === 'donated'
                    ? Math.max(1, Math.min(5, 1 + (e.amount || 0) / 50000))
                    : e.type === 'received_contract'
                        ? Math.max(1, Math.min(6, 1 + Math.sqrt((e.amount || e.value || 0) / 1e8)))
                        : 1.5;

                allEdges.push({
                    id: `edge-${i}`,
                    from: e.from,
                    to: e.to,
                    color: { color: edgeStyle.color, opacity: 0.6, highlight: edgeStyle.color },
                    dashes: edgeStyle.dashes,
                    width: edgeWidth,
                    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
                    title: `${e.type.replace(/_/g, ' ')}${e.amount ? ': ' + App.formatCurrency(e.amount) : ''}`,
                    edgeType: e.type,
                    edgeData: e,
                    smooth: { type: 'continuous' },
                });
            });
        }
    }

    function createNetwork() {
        nodesDataset = new vis.DataSet(allNodes);
        edgesDataset = new vis.DataSet(allEdges);

        const options = {
            nodes: {
                font: { color: '#ccc', size: 11, face: 'Inter, sans-serif' },
            },
            edges: {
                font: { color: '#888', size: 9, face: 'Inter, sans-serif', strokeWidth: 0 },
                smooth: { type: 'continuous' },
            },
            physics: {
                enabled: true,
                solver: 'forceAtlas2Based',
                forceAtlas2Based: {
                    gravitationalConstant: -60,
                    centralGravity: 0.01,
                    springLength: 120,
                    springConstant: 0.04,
                    damping: 0.4,
                },
                stabilization: {
                    enabled: true,
                    iterations: 200,
                    updateInterval: 25,
                },
            },
            interaction: {
                hover: true,
                tooltipDelay: 200,
                zoomView: true,
                dragView: true,
                multiselect: true,
            },
            layout: {
                improvedLayout: allNodes.length < 100,
            },
        };

        network = new vis.Network(container, { nodes: nodesDataset, edges: edgesDataset }, options);

        network.on('click', function (params) {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                const node = allNodes.find(n => n.id === nodeId);
                if (node) showNodeInfo(node);
            }
        });

        network.on('doubleClick', function (params) {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                network.focus(nodeId, { scale: 1.5, animation: { duration: 500 } });
            }
        });
    }

    function showNodeInfo(node) {
        const d = node.entityData;
        let html = '';

        html += `<div class="info-row"><span class="info-label">Type</span><span class="info-value">${node.entityType}</span></div>`;

        if (node.entityType === 'person') {
            if (d.role) html += `<div class="info-row"><span class="info-label">Role</span><span class="info-value">${d.role}</span></div>`;
            if (d.firm) html += `<div class="info-row"><span class="info-label">Firm</span><span class="info-value">${d.firm}</span></div>`;
            if (d.type) html += `<div class="info-row"><span class="info-label">Category</span><span class="info-value">${d.type}</span></div>`;
            if (d.integrity_violations) {
                html += `<div class="info-row"><span class="info-label">Integrity</span><span class="info-value"><span class="connection-badge badge-violation">Violations Found</span></span></div>`;
            }

            // Elections Ontario donations
            if (d.donations_pc_total) {
                html += '<div class="info-section"><h4>Elections Ontario Donations</h4>';
                html += `<div class="info-row"><span class="info-label">PC Party total</span><span class="info-value">${App.formatCurrency(d.donations_pc_total)}</span></div>`;
                if (d.donations_all_total && d.donations_all_total !== d.donations_pc_total) {
                    html += `<div class="info-row"><span class="info-label">All parties</span><span class="info-value">${App.formatCurrency(d.donations_all_total)}</span></div>`;
                }
                if (d.top_donations && d.top_donations.length > 0) {
                    d.top_donations.slice(0, 3).forEach(don => {
                        html += `<div class="info-row"><span class="info-label">${don.year}</span><span class="info-value">${App.formatCurrency(don.amount)} → ${don.recipient}</span></div>`;
                    });
                }
                html += '</div>';
            }

            // Sunshine List
            if (d.sunshine_top_salary) {
                html += '<div class="info-section"><h4>Sunshine List (Public Sector Salary)</h4>';
                html += `<div class="info-row"><span class="info-label">Highest salary</span><span class="info-value">${d.sunshine_top_salary}</span></div>`;
                html += `<div class="info-row"><span class="info-label">Employer</span><span class="info-value">${d.sunshine_top_employer} (${d.sunshine_top_year})</span></div>`;
                if (d.sunshine_top_title) html += `<div class="info-row"><span class="info-label">Title</span><span class="info-value">${d.sunshine_top_title}</span></div>`;
                html += `<div class="info-row"><span class="info-label">Records found</span><span class="info-value">${d.sunshine_total_records} across ${(d.sunshine_years || []).length} years</span></div>`;
                html += '</div>';
            }

            // Lobbyist registrations (as lobbyist)
            if (d.lobbyist_client_count) {
                html += '<div class="info-section"><h4>Lobbyist Registry (as lobbyist)</h4>';
                html += `<div class="info-row"><span class="info-label">Client registrations</span><span class="info-value">${d.lobbyist_client_count}+</span></div>`;
                if (d.lobbyist_clients && d.lobbyist_clients.length > 0) {
                    const active = d.lobbyist_clients.filter(c => c.status && c.status.toLowerCase() === 'active');
                    const shown = active.length > 0 ? active : d.lobbyist_clients;
                    shown.slice(0, 5).forEach(c => {
                        const badge = c.status && c.status.toLowerCase() === 'active' ? ' ●' : '';
                        html += `<div class="info-row"><span class="info-label">${c.client}</span><span class="info-value">${c.firm}${badge}</span></div>`;
                    });
                    if (d.lobbyist_clients.length > 5) html += `<div class="info-row"><span class="info-label">+ ${d.lobbyist_clients.length - 5} more</span></div>`;
                }
                html += '</div>';
            }

            // Curated clients (from original data)
            if (d.clients && d.clients.length > 0) {
                html += '<div class="info-section"><h4>Key Clients (documented)</h4>';
                d.clients.forEach(cid => {
                    const comp = DataLoader.getCompany(cid);
                    html += `<div class="info-row"><span class="info-value">${comp ? comp.name : cid}</span></div>`;
                });
                html += '</div>';
            }

            // Evidence sources
            if (d.evidence_sources && d.evidence_sources.length > 0) {
                html += `<div class="info-row" style="margin-top:8px;"><span class="info-label">Data sources</span><span class="info-value">${d.evidence_count}/4: ${d.evidence_sources.join(', ')}</span></div>`;
            }
        } else if (node.entityType === 'company') {
            if (d.total_gov_value) html += `<div class="info-row"><span class="info-label">Gov Value</span><span class="info-value">${App.formatCurrency(d.total_gov_value)}</span></div>`;
            if (d.donations_pc) html += `<div class="info-row"><span class="info-label">PC Donations</span><span class="info-value">${App.formatCurrency(d.donations_pc)}</span></div>`;
            if (d.connection_strength) {
                html += `<div class="info-row"><span class="info-label">Connection</span><span class="info-value"><span class="connection-badge badge-${d.connection_strength}">${d.connection_strength}</span></span></div>`;
            }

            // Public Accounts payments
            if (d.public_accounts_total) {
                html += '<div class="info-section"><h4>Public Accounts (actual payments)</h4>';
                html += `<div class="info-row"><span class="info-label">Total received</span><span class="info-value">${App.formatCurrency(d.public_accounts_total)}</span></div>`;
                if (d.public_accounts_years) {
                    Object.entries(d.public_accounts_years).forEach(([year, amt]) => {
                        html += `<div class="info-row"><span class="info-label">${year}</span><span class="info-value">${App.formatCurrency(amt)}</span></div>`;
                    });
                }
                if (d.public_accounts_ministries && d.public_accounts_ministries.length > 0) {
                    d.public_accounts_ministries.forEach(m => {
                        html += `<div class="info-row"><span class="info-label">${m.ministry}</span><span class="info-value">${App.formatCurrency(m.total)}</span></div>`;
                    });
                }
                html += '</div>';
            }

            // Lobbyist registrations
            if (d.lobbyist_count) {
                html += '<div class="info-section"><h4>Lobbyist Registry</h4>';
                html += `<div class="info-row"><span class="info-label">Registrations</span><span class="info-value">${d.lobbyist_count}</span></div>`;
                if (d.lobbyist_firms && d.lobbyist_firms.length > 0) {
                    html += `<div class="info-row"><span class="info-label">Active firms</span><span class="info-value">${d.lobbyist_firms.join(', ')}</span></div>`;
                }
                if (d.lobbyist_registrations && d.lobbyist_registrations.length > 0) {
                    const active = d.lobbyist_registrations.filter(r => r.status && r.status.toLowerCase() === 'active');
                    const shown = active.length > 0 ? active : d.lobbyist_registrations;
                    shown.slice(0, 5).forEach(r => {
                        html += `<div class="info-row"><span class="info-label">${r.lobbyist}</span><span class="info-value">${r.firm} (${r.status})</span></div>`;
                    });
                    if (d.lobbyist_registrations.length > 5) html += `<div class="info-row"><span class="info-label">+ ${d.lobbyist_registrations.length - 5} more</span></div>`;
                }
                html += '</div>';
            }

            // Contracts
            const contracts = DataLoader.getCompanyContracts(d.id);
            if (contracts.length > 0) {
                html += '<div class="info-section"><h4>Contracts</h4>';
                contracts.forEach(c => {
                    html += `<div class="info-row"><span class="info-label">${c.name}</span><span class="info-value">${App.formatCurrency(c.value)}</span></div>`;
                });
                html += '</div>';
            }

            // Evidence sources
            if (d.evidence_sources && d.evidence_sources.length > 0) {
                html += `<div class="info-row" style="margin-top:8px;"><span class="info-label">Data sources</span><span class="info-value">${d.evidence_count}/4: ${d.evidence_sources.join(', ')}</span></div>`;
            }
        }

        // Show connected edges
        const edges = DataLoader.getNodeEdges(d.id);
        if (edges.length > 0) {
            html += '<div class="info-section"><h4>Connections</h4>';
            edges.slice(0, 15).forEach(e => {
                const other = e.from === d.id ? e.to : e.from;
                html += `<div class="info-row"><span class="info-label">${e.type.replace(/_/g, ' ')}</span><span class="info-value">${other.replace(/-/g, ' ')}</span></div>`;
            });
            if (edges.length > 15) html += `<div class="info-row"><span class="info-label">+ ${edges.length - 15} more</span></div>`;
            html += '</div>';
        }

        App.setInfoPanel(d.name || node.label, html);
    }

    function bindFilters() {
        // Edge type checkboxes
        document.querySelectorAll('#network-filters input[data-edge]').forEach(cb => {
            cb.addEventListener('change', applyFilters);
        });

        // Min contract value slider
        const slider = document.getElementById('min-contract-value');
        const label = document.getElementById('min-contract-label');
        slider.addEventListener('input', function () {
            label.textContent = App.formatCurrency(parseInt(this.value));
            applyFilters();
        });

        // Scandal filter
        document.getElementById('scandal-filter').addEventListener('change', applyFilters);

        // Network search
        document.getElementById('network-search').addEventListener('input', function () {
            const q = this.value.toLowerCase();
            if (q.length < 2) return;
            const match = allNodes.find(n => n.label.toLowerCase().includes(q));
            if (match && network) {
                network.selectNodes([match.id]);
                network.focus(match.id, { scale: 1.2, animation: { duration: 500 } });
            }
        });

        // Reset
        document.getElementById('network-reset').addEventListener('click', function () {
            document.querySelectorAll('#network-filters input[data-edge]').forEach(cb => cb.checked = true);
            document.getElementById('min-contract-value').value = 0;
            document.getElementById('min-contract-label').textContent = '$0';
            document.getElementById('scandal-filter').value = 'all';
            document.getElementById('network-search').value = '';
            applyFilters();
            if (network) network.fit({ animation: { duration: 500 } });
        });
    }

    function applyFilters() {
        if (!network) return;

        const activeEdgeTypes = new Set();
        document.querySelectorAll('#network-filters input[data-edge]:checked').forEach(cb => {
            activeEdgeTypes.add(cb.dataset.edge);
        });

        const minValue = parseInt(document.getElementById('min-contract-value').value) || 0;
        const scandalFilter = document.getElementById('scandal-filter').value;

        // Filter edges
        const filteredEdges = allEdges.filter(e => {
            if (!activeEdgeTypes.has(e.edgeType)) return false;
            if (e.edgeType === 'received_contract' && (e.edgeData.amount || e.edgeData.value || 0) < minValue) return false;
            return true;
        });

        // Determine visible nodes (connected to at least one visible edge, or matching scandal filter)
        const visibleNodeIds = new Set();
        filteredEdges.forEach(e => {
            visibleNodeIds.add(e.from);
            visibleNodeIds.add(e.to);
        });

        // Scandal filter: filter by tag/association
        let filteredNodes = allNodes;
        if (scandalFilter !== 'all') {
            filteredNodes = allNodes.filter(n => {
                // Check if node has scandal tags in entity data
                const d = n.entityData;
                if (d.scandal && d.scandal.includes(scandalFilter)) return true;
                if (d.tags && d.tags.includes(scandalFilter)) return true;
                // Check connected edges
                const nodeEdges = allEdges.filter(e => e.from === n.id || e.to === n.id);
                return nodeEdges.some(e => {
                    const ed = e.edgeData;
                    return (ed.scandal && ed.scandal.includes(scandalFilter)) ||
                           (ed.tags && ed.tags.includes(scandalFilter));
                });
            });
            // If scandal filter returned nothing, show all
            if (filteredNodes.length === 0) filteredNodes = allNodes;
        }

        // Apply to datasets
        const finalNodeIds = scandalFilter === 'all'
            ? new Set(allNodes.map(n => n.id))
            : new Set(filteredNodes.map(n => n.id));

        nodesDataset.clear();
        nodesDataset.add(allNodes.filter(n => finalNodeIds.has(n.id)));

        edgesDataset.clear();
        edgesDataset.add(filteredEdges.filter(e => finalNodeIds.has(e.from) && finalNodeIds.has(e.to)));
    }

    function focusOnEntity(entityId) {
        if (!network || !initialized) return;
        const node = allNodes.find(n => n.id === entityId);
        if (node) {
            network.selectNodes([entityId]);
            network.focus(entityId, { scale: 1.5, animation: { duration: 500 } });
            showNodeInfo(node);
        }
    }

    function onResize() {
        if (network) {
            network.redraw();
            network.fit();
        }
    }

    return { init, render: onResize, focusOnEntity };
})();
