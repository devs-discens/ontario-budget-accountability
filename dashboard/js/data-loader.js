/**
 * Data Loader — fetches all JSON files and builds cross-reference indexes.
 */
const DataLoader = (function () {
    const DATA_DIR = 'data/';

    let revenue = null;
    let expenses = null;
    let contracts = null;
    let companies = null;
    let people = null;
    let connections = null;

    // Cross-reference indexes
    const idx = {
        contractById: {},
        companyById: {},
        personById: {},
        contractsByCompany: {},
        companiesByPerson: {},
        edgesByNode: {},
        contractsBySector: {},
    };

    async function fetchJSON(filename) {
        try {
            const resp = await fetch(DATA_DIR + filename);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            return await resp.json();
        } catch (e) {
            console.warn(`Could not load ${filename}:`, e.message);
            return null;
        }
    }

    async function loadAll() {
        const [rev, exp, con, comp, ppl, conn] = await Promise.all([
            fetchJSON('revenue.json'),
            fetchJSON('expenses.json'),
            fetchJSON('contracts.json'),
            fetchJSON('companies.json'),
            fetchJSON('people.json'),
            fetchJSON('connections.json'),
        ]);

        revenue = rev;
        expenses = exp;
        contracts = con;
        companies = comp;
        people = ppl;
        connections = conn;

        buildIndexes();

        return { revenue, expenses, contracts, companies, people, connections };
    }

    function buildIndexes() {
        // Index contracts
        if (contracts && contracts.contracts) {
            contracts.contracts.forEach(c => {
                idx.contractById[c.id] = c;
                if (c.sector) {
                    if (!idx.contractsBySector[c.sector]) idx.contractsBySector[c.sector] = [];
                    idx.contractsBySector[c.sector].push(c);
                }
                if (c.companies) {
                    c.companies.forEach(compId => {
                        if (!idx.contractsByCompany[compId]) idx.contractsByCompany[compId] = [];
                        idx.contractsByCompany[compId].push(c);
                    });
                }
            });
        }

        // Index companies
        if (companies && companies.companies) {
            companies.companies.forEach(c => {
                idx.companyById[c.id] = c;
                if (c.lobbyists) {
                    c.lobbyists.forEach(pid => {
                        if (!idx.companiesByPerson[pid]) idx.companiesByPerson[pid] = [];
                        idx.companiesByPerson[pid].push(c);
                    });
                }
            });
        }

        // Index people
        if (people && people.people) {
            people.people.forEach(p => {
                idx.personById[p.id] = p;
            });
        }

        // Index connections/edges (handle both "edges" and "connections" keys)
        const edgeList = connections && (connections.edges || connections.connections);
        if (edgeList) {
            edgeList.forEach(e => {
                if (!idx.edgesByNode[e.from]) idx.edgesByNode[e.from] = [];
                idx.edgesByNode[e.from].push(e);
                if (!idx.edgesByNode[e.to]) idx.edgesByNode[e.to] = [];
                idx.edgesByNode[e.to].push(e);
            });
        }
    }

    // Query functions
    function getContract(id) {
        return idx.contractById[id] || null;
    }

    function getCompany(id) {
        return idx.companyById[id] || null;
    }

    function getPerson(id) {
        return idx.personById[id] || null;
    }

    function getCompanyContracts(companyId) {
        return idx.contractsByCompany[companyId] || [];
    }

    function getPersonConnections(personId) {
        return idx.edgesByNode[personId] || [];
    }

    function getNodeEdges(nodeId) {
        return idx.edgesByNode[nodeId] || [];
    }

    function getContractsForSector(sectorId) {
        return idx.contractsBySector[sectorId] || [];
    }

    function getCompanyForContract(contractId) {
        const c = idx.contractById[contractId];
        if (!c || !c.companies) return [];
        return c.companies.map(id => idx.companyById[id]).filter(Boolean);
    }

    /**
     * Search across all entity types. Returns array of { type, id, name, data }.
     */
    function search(query) {
        if (!query || query.length < 2) return [];
        const q = query.toLowerCase();
        const results = [];

        if (companies && companies.companies) {
            companies.companies.forEach(c => {
                if (c.name.toLowerCase().includes(q)) {
                    results.push({ type: 'company', id: c.id, name: c.name, data: c });
                }
            });
        }

        if (people && people.people) {
            people.people.forEach(p => {
                if (p.name.toLowerCase().includes(q)) {
                    results.push({ type: 'person', id: p.id, name: p.name, data: p });
                }
            });
        }

        if (contracts && contracts.contracts) {
            contracts.contracts.forEach(c => {
                if (c.name.toLowerCase().includes(q)) {
                    results.push({ type: 'contract', id: c.id, name: c.name, data: c });
                }
            });
        }

        // Also search expense sectors and subcategories
        if (expenses && expenses.sectors) {
            expenses.sectors.forEach(s => {
                if (s.name.toLowerCase().includes(q)) {
                    results.push({ type: 'sector', id: s.id, name: s.name, data: s });
                }
                if (s.subcategories) {
                    s.subcategories.forEach(sub => {
                        if (sub.name.toLowerCase().includes(q)) {
                            results.push({ type: 'subcategory', id: sub.id, name: sub.name, data: sub, parent: s });
                        }
                    });
                }
            });
        }

        return results.slice(0, 20);
    }

    function getData() {
        return { revenue, expenses, contracts, companies, people, connections };
    }

    return {
        loadAll,
        getData,
        getContract,
        getCompany,
        getPerson,
        getCompanyContracts,
        getPersonConnections,
        getNodeEdges,
        getContractsForSector,
        getCompanyForContract,
        search,
        idx,
    };
})();
