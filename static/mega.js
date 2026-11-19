const form = document.querySelector('#mega-form');
const runButton = document.querySelector('#mega-run');
const pauseButton = document.querySelector('#mega-pause');
const endButton = document.querySelector('#mega-end');
const statusText = document.querySelector('#mega-status');
const errorText = document.querySelector('#mega-error');
const log = document.querySelector('#mega-log');

const statusMessages = {
    idle: 'Ready to run.',
    running: 'Bot is running…',
    pausing: 'Pausing after the current operation…',
    paused: 'Bot paused.',
    ending: 'Ending after the current operation…',
    ended: 'Run ended.',
    finished: 'Run finished.',
    failed: 'Run failed. See the upload log for details.',
};

let status = 'idle';
let busy = false;
let pollTimer;

function renderControls() {
    const active = ['running', 'pausing', 'paused', 'ending'].includes(status);
    runButton.disabled = busy || active;
    pauseButton.disabled = busy || !['running', 'paused'].includes(status);
    pauseButton.textContent = status === 'paused' ? 'Resume' : 'Pause';
    endButton.disabled = busy || !active || status === 'ending';
    statusText.textContent = statusMessages[status];
    return active;
}

async function requestBot(action = '', data) {
    const options = { cache: 'no-store' };
    if (data !== undefined) {
        options.method = 'POST';
        options.headers = { 'Content-Type': 'application/json' };
        options.body = JSON.stringify(data);
    }
    const response = await fetch('/api/mega' + action, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(result.error || 'Could not reach the MEGA bot. Check that the updated app is running.');
    }
    return result;
}

function showError(message) {
    errorText.textContent = message;
    errorText.hidden = !message;
}

async function pollActivity() {
    if (busy) return;
    try {
        const result = await requestBot();
        if (busy) return;
        status = result.status;
        const output = result.logs.join('\n');
        if (log.textContent !== output) {
            log.textContent = output;
            log.hidden = !output;
            log.scrollTop = log.scrollHeight;
        }
        if (renderControls()) {
            pollTimer = setTimeout(pollActivity, 1000);
        }
    } catch (error) {
        showError(error.message);
        if (renderControls()) {
            pollTimer = setTimeout(pollActivity, 2000);
        }
    }
}

async function submitAction(action, data) {
    clearTimeout(pollTimer);
    busy = true;
    showError('');
    renderControls();
    try {
        const result = await requestBot(action, data);
        status = result.status;
    } catch (error) {
        showError(error.message);
    } finally {
        busy = false;
        renderControls();
        await pollActivity();
    }
}

form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitAction('', Object.fromEntries(new FormData(form)));
});
pauseButton.addEventListener('click', () => {
    submitAction(status === 'paused' ? '/resume' : '/pause', {});
});
endButton.addEventListener('click', () => submitAction('/end', {}));

pollActivity();

const runHistory = document.querySelector('#mega-run-history');
const artistRows = document.querySelector('#mega-artist-rows');
let analyticsBusy = false;

function formatUploadSize(bytes) {
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
    return (bytes / 1e6).toFixed(1) + ' MB';
}

async function updateAnalytics() {
    if (analyticsBusy) return;
    analyticsBusy = true;
    try {
        const query = runHistory.value ? '?run=' + encodeURIComponent(runHistory.value) : '';
        const response = await fetch('/api/mega/analytics' + query, { cache: 'no-store' });
        if (!response.ok) throw new Error('Upload analytics are temporarily unavailable.');
        const result = await response.json();
        const selected = runHistory.value;
        if (query !== (selected ? '?run=' + encodeURIComponent(selected) : '')) return;
        runHistory.replaceChildren(new Option('Latest run', ''));
        for (const run of result.history) {
            runHistory.add(new Option(new Date(run.started).toLocaleString(), run.id));
        }
        runHistory.value = selected;
        const run = result.run;
        if (!run) return;
        const context = run.current_artist
            ? 'Current artist · ' + run.current_artist
            : (statusMessages[run.status] || run.status);
        document.querySelector('#mega-analytics-context').textContent =
            context + ' · Started ' + new Date(run.started).toLocaleString();
        document.querySelector('#mega-analytics-partial').hidden = !run.partial;
        document.querySelector('#mega-count-uploaded').textContent = run.uploaded;
        document.querySelector('#mega-count-skipped').textContent = run.skipped;
        document.querySelector('#mega-count-failed').textContent = run.failed;
        document.querySelector('#mega-count-artists').textContent = run.completed_artists;
        document.querySelector('#mega-count-size').textContent =
            run.partial ? 'Unavailable' : formatUploadSize(run.uploaded_bytes);
        const labels = {
            searching: 'Searching', processing: 'In progress', complete: 'Batch complete',
            no_matches: 'No matches', search_failed: 'Search failed', interrupted: 'Interrupted',
        };
        const rows = run.artists.map(artist => {
            const row = document.createElement('tr');
            const label = artist.status === 'complete' && artist.failed
                ? 'Finished with errors' : labels[artist.status];
            for (const text of [
                artist.name, label,
                artist.candidates ? artist.processed + ' / ' + artist.candidates : artist.processed,
                artist.uploaded, artist.skipped, artist.failed,
            ]) {
                const cell = document.createElement('td');
                cell.textContent = text;
                row.append(cell);
            }
            return row;
        });
        if (!rows.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 6;
            cell.textContent = 'Waiting for the first artist…';
            row.append(cell);
            rows.push(row);
        }
        artistRows.replaceChildren(...rows);
    } catch (error) {
        document.querySelector('#mega-analytics-context').textContent = error.message;
    } finally {
        analyticsBusy = false;
    }
}

runHistory.addEventListener('change', updateAnalytics);
updateAnalytics();
setInterval(updateAnalytics, 3000);
