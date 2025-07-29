const script = document.createElement('script');
script.src = 'https://telegram.org/js/telegram-web-app.js';
script.onload = () => console.log('Telegram Web App SDK loaded');
document.head.appendChild(script);

const pages = document.querySelectorAll('.page');
const navButtons = document.querySelectorAll('.nav-btn');
const botInfo = document.getElementById('bot-info');
const botActions = document.getElementById('bot-actions');
const botError = document.getElementById('bot-error');
const serversList = document.getElementById('servers-list');
const startBtn = document.getElementById('start-btn');
const stopBtn = document.getElementById('stop-btn');
const restartBtn = document.getElementById('restart-btn');
const deleteBtn = document.getElementById('delete-btn');

function switchPage(pageId) {
  pages.forEach(page => page.classList.toggle('active', page.id === pageId));
  navButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.page === pageId));
}

navButtons.forEach(btn => {
  btn.addEventListener('click', () => switchPage(btn.dataset.page));
});

async function fetchBotInfo() {
  try {
    const initData = window.Telegram.WebApp.initData;
    if (!initData) {
      botError.textContent = 'Ошибка: Запустите приложение через Telegram';
      botError.classList.remove('hidden');
      return;
    }

    const response = await fetch('/get_userbot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData })
    });
    const data = await response.json();

    if (data.success && data.userbot) {
      const { ub_username, status, server_ip, ub_type, hikka_path, blocked } = data.userbot;
      botInfo.innerHTML = `
        <p><strong>Юзернейм:</strong> @${ub_username}</p>
        <p><strong>Статус:</strong> ${status === 'running' ? 'Запущен' : status === 'stopped' ? 'Остановлен' : 'Ошибка'}</p>
        <p><strong>Сервер:</strong> ${server_ip}</p>
        <p><strong>Тип:</strong> ${ub_type}</p>
        <p><strong>Путь:</strong> ${hikka_path}</p>
        <p><strong>Блокировка:</strong> ${blocked ? 'Заблокирован' : 'Активен'}</p>
      `;
      botInfo.classList.remove('hidden');
      botActions.classList.remove('hidden');
      botError.classList.add('hidden');

      startBtn.disabled = status === 'running';
      stopBtn.disabled = status === 'stopped';
      restartBtn.disabled = status !== 'running';
    } else {
      botInfo.classList.add('hidden');
      botActions.classList.add('hidden');
      botError.textContent = data.message || 'Юзербот не найден';
      botError.classList.remove('hidden');
    }
  } catch (error) {
    botError.textContent = `Ошибка: ${error.message}`;
    botError.classList.remove('hidden');
  }
}

async function manageBot(action) {
  try {
    const initData = window.Telegram.WebApp.initData;
    const response = await fetch('/manage_userbot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData, action })
    });
    const data = await response.json();

    if (data.success) {
      await fetchBotInfo();
      botError.classList.add('hidden');
    } else {
      botError.textContent = data.message || 'Ошибка выполнения действия';
      botError.classList.remove('hidden');
    }
  } catch (error) {
    botError.textContent = `Ошибка: ${error.message}`;
    botError.classList.remove('hidden');
  }
}

async function fetchServersStatus() {
  try {
    const response = await fetch('/get_servers_status');
    const data = await response.json();

    if (data.success) {
      serversList.innerHTML = data.servers.map(server => `
        <div class="server-card">
          <h3>Сервер: ${server.ip}</h3>
          <p><strong>CPU:</strong> ${server.stats.cpu_usage}%</p>
          <p><strong>RAM:</strong> ${server.stats.ram_used} / ${server.stats.ram_total} (${server.stats.ram_percent}%)</p>
          <p><strong>Диск:</strong> ${server.stats.disk_used} / ${server.stats.disk_total} (${server.stats.disk_percent})</p>
          <p><strong>Время работы:</strong> ${server.stats.uptime}</p>
        </div>
      `).join('');
    } else {
      serversList.innerHTML = `<p class="error">${data.message || 'Ошибка загрузки данных'}</p>`;
    }
  } catch (error) {
    serversList.innerHTML = `<p class="error">Ошибка: ${error.message}</p>`;
  }
}

startBtn.addEventListener('click', () => manageBot('start'));
stopBtn.addEventListener('click', () => manageBot('stop'));
restartBtn.addEventListener('click', () => manageBot('restart'));
deleteBtn.addEventListener('click', () => {
  if (confirm('Вы уверены, что хотите удалить юзербот?')) manageBot('delete');
});

window.addEventListener('load', () => {
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.ready();
    switchPage('home');
    fetchBotInfo();
    fetchServersStatus();
  }
});