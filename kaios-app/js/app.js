// Vanilla JS, ES5/ES6-safe (no async/await, no optional chaining) to stay
// compatible with older KaiOS 2.5 (Gecko 48) devices, not just KaiOS 3.x.

var STORAGE_KEY = 'telelite_token';
var MESSAGES_PER_PAGE = 20;

var focusables = [];
var screenActions = { left: null, center: null, right: null, back: null };

// ---- storage ----

function getToken() {
  return localStorage.getItem(STORAGE_KEY);
}

function setToken(token) {
  localStorage.setItem(STORAGE_KEY, token);
}

function clearToken() {
  localStorage.removeItem(STORAGE_KEY);
}

// ---- generic UI helpers ----

function showError(msg) {
  var banner = document.getElementById('error-banner');
  if (msg) {
    banner.textContent = msg;
    banner.classList.remove('hidden');
  } else {
    banner.textContent = '';
    banner.classList.add('hidden');
  }
}

function showScreen(id) {
  var screens = document.querySelectorAll('.screen');
  for (var i = 0; i < screens.length; i++) {
    screens[i].classList.add('hidden');
  }
  document.getElementById(id).classList.remove('hidden');
}

function setSoftkeys(left, center, right) {
  document.getElementById('sk-left').textContent = left || '';
  document.getElementById('sk-center').textContent = center || '';
  document.getElementById('sk-right').textContent = right || '';
}

function setFocusables(elements) {
  focusables = elements;
  if (elements.length > 0) {
    elements[0].focus();
  }
}

function moveFocus(delta) {
  if (focusables.length === 0) {
    return;
  }
  var idx = focusables.indexOf(document.activeElement);
  if (idx === -1) {
    idx = 0;
  }
  var next = idx + delta;
  if (next < 0) {
    next = 0;
  }
  if (next >= focusables.length) {
    next = focusables.length - 1;
  }
  focusables[next].focus();
}

// ---- key handling: D-pad + KaiOS softkeys ----

document.addEventListener('keydown', function (e) {
  var key = e.key;
  var active = document.activeElement;

  if (key === 'ArrowUp') {
    moveFocus(-1);
    e.preventDefault();
  } else if (key === 'ArrowDown') {
    moveFocus(1);
    e.preventDefault();
  } else if (key === 'Enter') {
    if (active && active.tagName === 'TEXTAREA') {
      return; // let Enter insert a newline in the reply box
    }
    if (active && active._onActivate) {
      active._onActivate();
      e.preventDefault();
    } else if (screenActions.center) {
      screenActions.center();
      e.preventDefault();
    }
  } else if (key === 'SoftLeft') {
    if (screenActions.left) {
      screenActions.left();
      e.preventDefault();
    }
  } else if (key === 'SoftRight') {
    if (screenActions.right) {
      screenActions.right();
      e.preventDefault();
    }
  } else if (key === 'Backspace') {
    var editingText = active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA');
    if (!editingText && screenActions.back) {
      screenActions.back();
      e.preventDefault();
    }
  }
});

// Real KaiOS softkeys are physical buttons (SoftLeft/SoftRight keydown
// events above) that a desktop keyboard can't generate, so click handlers
// are added too — lets this be tested with a mouse, and doesn't hurt on
// touch-capable KaiOS devices either.
document.getElementById('sk-left').addEventListener('click', function () {
  if (screenActions.left) {
    screenActions.left();
  }
});
document.getElementById('sk-center').addEventListener('click', function () {
  if (screenActions.center) {
    screenActions.center();
  }
});
document.getElementById('sk-right').addEventListener('click', function () {
  if (screenActions.right) {
    screenActions.right();
  }
});

// ---- API access ----

function apiFetch(path, options) {
  options = options || {};
  options.headers = options.headers || {};
  var token = getToken();
  if (token) {
    options.headers['Authorization'] = 'Bearer ' + token;
  }
  if (options.body && typeof options.body !== 'string') {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  return fetch(API_BASE_URL + path, options).then(function (resp) {
    if (resp.status === 401) {
      clearToken();
      renderLoginPhone();
      throw new Error('session_expired');
    }
    return resp.json().then(function (data) {
      return { ok: resp.ok, status: resp.status, data: data };
    });
  });
}

function handleNetworkError(err) {
  if (err.message !== 'session_expired') {
    showError('Network error, please try again.');
  }
}

// ---- screens ----

function renderLoginPhone(errorMsg) {
  showScreen('screen-login-phone');
  document.getElementById('header-title').textContent = 'TeleLite';
  showError(errorMsg);
  var input = document.getElementById('phone-input');
  input.value = '';
  screenActions = { left: null, center: submitPhone, right: null, back: null };
  setSoftkeys('', 'Send', '');
  setFocusables([input]);
}

function submitPhone() {
  var phone = document.getElementById('phone-input').value.trim();
  if (!phone) {
    showError('Phone number is required.');
    return;
  }
  showError('Sending code...');
  apiFetch('/login/request', { method: 'POST', body: { phone_number: phone } })
    .then(function (res) {
      if (!res.ok) {
        showError(res.data.message || res.data.error);
        return;
      }
      renderLoginCode(res.data.pending_id, phone);
    })
    .catch(handleNetworkError);
}

function renderLoginCode(pendingId, phoneNumber, errorMsg, needsPassword) {
  showScreen('screen-login-code');
  document.getElementById('header-title').textContent = 'TeleLite';
  showError(errorMsg);

  var codeInput = document.getElementById('code-input');
  codeInput.value = '';
  var pwField = document.getElementById('password-field');
  var pwInput = document.getElementById('password-input');
  if (needsPassword) {
    pwField.classList.remove('hidden');
    pwInput.value = '';
  } else {
    pwField.classList.add('hidden');
  }

  screenActions = {
    left: renderLoginPhone,
    center: function () {
      submitCode(pendingId, phoneNumber, needsPassword);
    },
    right: null,
    back: renderLoginPhone,
  };
  setSoftkeys('Back', 'Verify', '');
  setFocusables(needsPassword ? [codeInput, pwInput] : [codeInput]);
}

function submitCode(pendingId, phoneNumber, hadPasswordField) {
  var code = document.getElementById('code-input').value.trim();
  var password = hadPasswordField ? document.getElementById('password-input').value : undefined;
  if (!code) {
    showError('Code is required.');
    return;
  }
  var body = { pending_id: pendingId, code: code };
  if (password) {
    body.password = password;
  }
  apiFetch('/login/verify', { method: 'POST', body: body })
    .then(function (res) {
      if (!res.ok) {
        var needsPw = res.data.error === 'needs_password';
        renderLoginCode(pendingId, phoneNumber, res.data.message || res.data.error, needsPw);
        return;
      }
      setToken(res.data.token);
      renderChats();
    })
    .catch(handleNetworkError);
}

function renderChats() {
  showScreen('screen-chats');
  document.getElementById('header-title').textContent = 'Chats';
  showError(null);
  var list = document.getElementById('chat-list');
  list.innerHTML = '';
  screenActions = { left: null, center: null, right: logoutAction, back: null };
  setSoftkeys('', '', 'Logout');
  setFocusables([]);

  apiFetch('/chats', { method: 'GET' })
    .then(function (res) {
      if (!res.ok) {
        showError(res.data.message || res.data.error);
        return;
      }
      var focusEls = [];
      res.data.chats.forEach(function (chat) {
        var li = document.createElement('li');
        li.setAttribute('tabindex', '0');
        li.textContent = chat.name + (chat.unread_count ? ' (' + chat.unread_count + ')' : '');
        li._onActivate = function () {
          renderConversation(chat.chat_id, chat.name, null, null, null, chat.can_reply !== false);
        };
        list.appendChild(li);
        focusEls.push(li);
      });
      setFocusables(focusEls);
    })
    .catch(handleNetworkError);
}

function logoutAction() {
  apiFetch('/logout', { method: 'POST' })
    .then(function () {
      clearToken();
      renderLoginPhone();
    })
    .catch(function () {
      // Best-effort revoke, same policy as the backend: always clear the
      // local session even if the network call itself failed.
      clearToken();
      renderLoginPhone();
    });
}

function renderConversation(chatId, chatName, beforeId, errorMsg, draftText, canReply) {
  showScreen('screen-conversation');
  document.getElementById('header-title').textContent = chatName;
  showError(errorMsg);

  var list = document.getElementById('message-list');
  list.innerHTML = '';
  var olderLink = document.getElementById('older-link');
  olderLink.classList.add('hidden');

  var replyContainer = document.getElementById('reply-container');
  var replyInput = document.getElementById('reply-input');
  replyInput.value = draftText || '';
  if (canReply) {
    replyContainer.classList.remove('hidden');
  } else {
    replyContainer.classList.add('hidden');
  }

  screenActions = {
    left: function () {
      renderChats();
    },
    center: null,
    right: canReply
      ? function () {
          submitReply(chatId, chatName, canReply);
        }
      : null,
    back: function () {
      renderChats();
    },
  };
  setSoftkeys('Back', '', canReply ? 'Send' : '');

  var qs = '?limit=' + MESSAGES_PER_PAGE + (beforeId ? '&before_id=' + beforeId : '');
  apiFetch('/chats/' + chatId + '/messages' + qs, { method: 'GET' })
    .then(function (res) {
      if (!res.ok) {
        showError(res.data.message || res.data.error);
        setFocusables(canReply ? [replyInput] : []);
        return;
      }
      var messages = res.data.messages;
      var focusEls = [];
      if (messages.length === MESSAGES_PER_PAGE) {
        var oldestId = messages[0].id;
        var olderItem = document.getElementById('older-item');
        olderItem.setAttribute('tabindex', '0');
        olderItem._onActivate = function () {
          renderConversation(chatId, chatName, oldestId, null, null, canReply);
        };
        olderLink.classList.remove('hidden');
        focusEls.push(olderItem);
      }
      messages.forEach(function (m) {
        var li = document.createElement('li');
        li.textContent = (m.out ? 'Me: ' : 'Them: ') + m.text;
        list.appendChild(li);
      });
      if (canReply) {
        focusEls.push(replyInput);
      }
      setFocusables(focusEls);
    })
    .catch(function (err) {
      handleNetworkError(err);
      setFocusables(canReply ? [replyInput] : []);
    });
}

function submitReply(chatId, chatName, canReply) {
  var text = document.getElementById('reply-input').value.trim();
  if (!text) {
    showError('Message text is required.');
    return;
  }
  apiFetch('/chats/' + chatId + '/messages', { method: 'POST', body: { text: text } })
    .then(function (res) {
      if (!res.ok) {
        renderConversation(chatId, chatName, null, res.data.message || res.data.error, text, canReply);
        return;
      }
      renderConversation(chatId, chatName, null, null, null, canReply);
    })
    .catch(function (err) {
      if (err.message !== 'session_expired') {
        renderConversation(chatId, chatName, null, 'Network error, please try again.', text, canReply);
      }
    });
}

// ---- init ----

document.addEventListener('DOMContentLoaded', function () {
  if (getToken()) {
    renderChats();
  } else {
    renderLoginPhone();
  }
});
