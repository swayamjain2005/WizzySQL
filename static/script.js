// DOM Elements
const connectionForm = document.getElementById('db-connection-form');
const mainContent = document.getElementById('main-content');
const sqlTab = document.getElementById('sql-tab');
const nlTab = document.getElementById('nl-tab');
const sqlTabContent = document.getElementById('sql-tab-content');
const nlTabContent = document.getElementById('nl-tab-content');
const executeSqlBtn = document.getElementById('execute-sql');
const askNlBtn = document.getElementById('ask-nl');
const resultsDiv = document.getElementById('results');

// Tab switching
document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', (e) => {
        // Update active tab
        document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active', 'border-blue-500', 'text-blue-600'));
        document.querySelectorAll('.tab-button').forEach(btn => btn.classList.add('border-transparent', 'text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300'));
        
        e.target.classList.add('active', 'border-blue-500', 'text-blue-600');
        e.target.classList.remove('border-transparent', 'text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300');
        
        // Show corresponding content
        document.querySelectorAll('.tab-content').forEach(content => content.classList.add('hidden'));
        if (e.target.id === 'sql-tab') {
            sqlTabContent.classList.remove('hidden');
        } else {
            nlTabContent.classList.remove('hidden');
        }
    });
});

// Handle database connection
connectionForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const connectionData = {
        host: document.getElementById('db-host').value,
        database: document.getElementById('db-name').value,
        user: document.getElementById('db-user').value,
        password: document.getElementById('db-password').value,
        ssl_disabled: document.getElementById('ssl-disabled').checked
    };

    try {
        const response = await fetch('/connect', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(connectionData)
        });

        const data = await response.json();
        
        if (response.ok) {
            // Show main content
            mainContent.classList.remove('hidden');
            connectionForm.closest('div').classList.add('hidden');
            showSuccess('Successfully connected to the database!');
        } else {
            showError(data.error || 'Failed to connect to the database');
        }
    } catch (error) {
        showError('Error connecting to the server: ' + error.message);
    }
});

// Handle SQL query execution
executeSqlBtn.addEventListener('click', async () => {
    const query = document.getElementById('sql-query').value.trim();
    if (!query) {
        showError('Please enter a SQL query');
        return;
    }

    await executeQuery(query, 'sql');
});

// Handle natural language query
askNlBtn.addEventListener('click', async () => {
    const query = document.getElementById('nl-query').value.trim();
    if (!query) {
        showError('Please enter a question');
        return;
    }

    await executeQuery(query, 'nl');
});

// Execute query (SQL or natural language)
async function executeQuery(query, type) {
    try {
        showLoading();
        
        const response = await fetch(`/query?type=${type}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query })
        });

        const data = await response.json();
        
        if (response.ok) {
            if (data.sql) {
                // Show the generated SQL for natural language queries
                const sqlInfo = document.createElement('div');
                sqlInfo.className = 'mb-4 p-3 bg-blue-50 text-blue-800 rounded-md text-sm';
                sqlInfo.innerHTML = `<strong>Generated SQL:</strong><br><code class="bg-white p-1 rounded">${data.sql}</code>`;
                resultsDiv.innerHTML = '';
                resultsDiv.appendChild(sqlInfo);
            } else {
                resultsDiv.innerHTML = '';
            }
            
            if (data.error) {
                showError(data.error);
            } else if (data.results) {
                displayResults(data.results);
            } else if (data.affected_rows !== undefined) {
                const message = document.createElement('p');
                message.textContent = `Query successful. ${data.affected_rows} row(s) affected.`;
                resultsDiv.appendChild(message);
            }
        } else {
            showError(data.error || 'Error executing query');
        }
    } catch (error) {
        showError('Error: ' + error.message);
    }
}

// Display query results in a table
function displayResults(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        resultsDiv.innerHTML = '<p>No results found.</p>';
        return;
    }

    // Create table
    const table = document.createElement('table');
    table.className = 'min-w-full divide-y divide-gray-200';
    
    // Create table header
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    
    // Get column names from first row
    const columns = Object.keys(data[0]);
    columns.forEach(col => {
        const th = document.createElement('th');
        th.className = 'px-6 py-3 bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider';
        th.textContent = col;
        headerRow.appendChild(th);
    });
    
    thead.appendChild(headerRow);
    table.appendChild(thead);
    
    // Create table body
    const tbody = document.createElement('tbody');
    tbody.className = 'bg-white divide-y divide-gray-200';
    
    // Add data rows
    data.forEach(row => {
        const tr = document.createElement('tr');
        columns.forEach(col => {
            const td = document.createElement('td');
            td.className = 'px-6 py-4 whitespace-nowrap text-sm text-gray-500';
            td.textContent = row[col] === null ? 'NULL' : row[col];
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    
    table.appendChild(tbody);
    
    // Clear previous results and add table
    if (resultsDiv.querySelector('p')) {
        resultsDiv.innerHTML = '';
    }
    resultsDiv.appendChild(table);
}

// Utility functions
function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'p-4 mb-4 text-red-700 bg-red-100 rounded-md';
    errorDiv.textContent = message;
    resultsDiv.innerHTML = '';
    resultsDiv.appendChild(errorDiv);
}

function showSuccess(message) {
    const successDiv = document.createElement('div');
    successDiv.className = 'p-4 mb-4 text-green-700 bg-green-100 rounded-md';
    successDiv.textContent = message;
    resultsDiv.innerHTML = '';
    resultsDiv.appendChild(successDiv);
}

function showLoading() {
    resultsDiv.innerHTML = '<p class="text-gray-500 italic">Executing query...</p>';
}

// Initialize
function init() {
    // Check if already connected (after page refresh)
    fetch('/check-connection')
        .then(response => response.json())
        .then(data => {
            if (data.connected) {
                mainContent.classList.remove('hidden');
                connectionForm.closest('div').classList.add('hidden');
            }
        });
}

// Initialize the app
init();
