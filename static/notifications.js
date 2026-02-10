const POLL_INTERVAL = 5000;
let seenIds = new Set();
let isFirstLoad = true;

async function checkNotifications() {
    try {
        const res = await fetch('/get-notifications');
        const data = await res.json();

        const unread = data.filter(n => !n.is_read);

        // 1. Update Badge
        const badge = document.getElementById('notif-badge');
        if (badge) {
            badge.innerText = unread.length;
            if (unread.length > 0) {
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }

        // 2. Populate Dropdown List
        const list = document.getElementById('notif-list');
        if (list) {
            if (data.length === 0) {
                list.innerHTML = '<div class="p-4 text-center text-xs text-slate-400">No notifications</div>';
            } else {
                list.innerHTML = data.map(n => `
                    <div class="px-4 py-3 border-b border-slate-100 hover:bg-slate-50 transition-colors ${!n.is_read ? 'bg-orange-50/60' : ''}">
                        <p class="text-sm text-slate-800 ${!n.is_read ? 'font-semibold' : ''}">${n.message}</p>
                        
                        ${n.link ? `
                        <div class="flex items-center gap-3 mt-1.5">
                            <a href="${n.link}" target="_blank" class="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1 font-medium bg-blue-50 px-2 py-1 rounded-md border border-blue-100 transition-colors">
                                View Solution <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
                            </a>
                            <button onclick="copyLink(event, '${n.link}')" class="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1 bg-white px-2 py-1 rounded-md border border-slate-200 transition-colors active:scale-95">
                                <i class="fa-regular fa-copy"></i> Copy
                            </button>
                        </div>
                        ` : ''}
                        
                        <span class="text-[10px] text-slate-400 block mt-1.5">${new Date(n.timestamp).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })}</span>
                    </div>
                `).join('');
            }
        }

        // 3. Show Toast logic
        if (isFirstLoad) {
            // First load: just mark all current unread as "seen" so we don't spam toasts
            unread.forEach(n => seenIds.add(n.id));
            isFirstLoad = false;
        } else {
            // Subsequent polls: Show toast for NEW unread only
            unread.forEach(n => {
                if (!seenIds.has(n.id)) {
                    seenIds.add(n.id);
                    // Use Toastify if available
                    if (typeof Toastify === 'function') {
                        // Play sound
                        const audio = document.getElementById('notification-sound');
                        if (audio) {
                            audio.play().catch(e => console.log("Audio play blocked:", e));
                        }

                        Toastify({
                            text: "🔔 " + n.message,
                            duration: 5000,
                            close: true,
                            gravity: "top",
                            position: "right",
                            backgroundColor: "linear-gradient(to right, #ea580c, #c2410c)",
                            stopOnFocus: true,
                            onClick: function () {
                                if (n.link) window.open(n.link, '_blank');
                            }
                        }).showToast();
                    }
                }
            });
        }

    } catch (err) {
        console.error("Polling error:", err);
    }
}

// Global function for the "Mark all read" button or Bell click
window.markAllRead = async function () {
    try {
        await fetch('/mark-all-read', { method: 'POST' });

        // Immediate UI update (optimistic)
        const badge = document.getElementById('notif-badge');
        if (badge) badge.classList.add('hidden');

        // Re-fetch to update the list styles (remove bold)
        setTimeout(checkNotifications, 300);

    } catch (err) {
        console.error("Error marking read:", err);
    }
};

// Copy Link Function
window.copyLink = function (event, link) {
    event.preventDefault(); // Prevent triggering other clicks if necessary
    if (!link) return;

    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(link).then(() => {
            showToast("Link copied to clipboard!", "success");
        }).catch(err => {
            console.error('Async: Could not copy text: ', err);
            fallbackCopyTextToClipboard(link);
        });
    } else {
        fallbackCopyTextToClipboard(link);
    }
};

function fallbackCopyTextToClipboard(text) {
    var textArea = document.createElement("textarea");
    textArea.value = text;

    // Avoid scrolling to bottom
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";

    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        var successful = document.execCommand('copy');
        var msg = successful ? 'successful' : 'unsuccessful';
        if (successful) {
            showToast("Link copied to clipboard!", "success");
        } else {
            showToast("Failed to copy link.", "error");
        }
    } catch (err) {
        console.error('Fallback: Oops, unable to copy', err);
        showToast("Failed to copy link.", "error");
    }

    document.body.removeChild(textArea);
}

// Helper for UI feedback
function showToast(msg, type = 'info') {
    if (typeof Toastify === 'function') {
        Toastify({
            text: msg,
            duration: 3000,
            close: true,
            gravity: "top",
            position: "center",
            backgroundColor: type === 'success' ? "#10b981" : "#ef4444",
        }).showToast();
    } else {
        alert(msg);
    }
}

// Start
document.addEventListener('DOMContentLoaded', checkNotifications);
setInterval(checkNotifications, POLL_INTERVAL);
