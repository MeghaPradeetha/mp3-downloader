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
