/**
 * OmniPilot Safe WhatsApp Bridge (127.0.0.1:3005 ONLY)
 * - Opt-in only: Boss scans QR manually via Perangkat Tertaut.
 * - Anti-ban safeguards: NEVER auto-replies on its own; only sends messages approved by Boss,
 *   with natural typing delay (2.5s - 5.5s) and minimum 10s cooldown between outbound messages.
 */

import express from "express";
import pino from "pino";
import qrcode from "qrcode-terminal";
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";

const HOST = "127.0.0.1";
const PORT = Number(process.env.WA_BRIDGE_PORT || 3005);
const MIN_SEND_INTERVAL_MS = 10_000;

let sock = null;
let isConnected = false;
let lastSendTimestamp = 0;
const unreadBuffer = [];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState("./auth_info");
  let version;
  try {
    const latest = await fetchLatestBaileysVersion();
    version = latest.version;
  } catch {
    version = undefined;
  }

  sock = makeWASocket({
    ...(version ? { version } : {}),
    auth: state,
    logger: pino({ level: "silent" }),
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      console.log("\n[WhatsApp Bridge] Scan QR di WhatsApp HP (Perangkat Tertaut):");
      qrcode.generate(qr, { small: true });
    }
    if (connection === "open") {
      isConnected = true;
      console.log("[WhatsApp Bridge] Terhubung dalam mode aman (Read + Approved Reply).");
    } else if (connection === "close") {
      isConnected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      if (statusCode !== DisconnectReason.loggedOut) {
        setTimeout(startWhatsApp, 5000);
      } else {
        console.log("[WhatsApp Bridge] Sesi logout. Hapus folder auth_info untuk scan ulang.");
      }
    }
  });

  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue;
      const body =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        msg.message.imageMessage?.caption ||
        "[Media/Lampiran]";
      unreadBuffer.unshift({
        id: msg.key.id,
        chatId: msg.key.remoteJid,
        sender: msg.pushName || msg.key.remoteJid,
        body,
        timestamp: new Date().toISOString(),
      });
      if (unreadBuffer.length > 100) unreadBuffer.pop();
    }
  });
}

const app = express();
app.use(express.json());

app.get("/status", (_req, res) => {
  res.json({
    connected: isConnected,
    bufferedUnread: unreadBuffer.length,
    mode: "human_in_the_loop_safe",
  });
});

app.get("/unread", (req, res) => {
  const limit = Math.min(50, Number(req.query.limit || 20));
  res.json({
    connected: isConnected,
    messages: unreadBuffer.slice(0, limit),
  });
});

app.post("/send", async (req, res) => {
  if (!isConnected || !sock) {
    return res.status(503).json({ error: "WhatsApp belum terhubung." });
  }
  const { chatId, text } = req.body || {};
  if (!chatId || !text) {
    return res.status(400).json({ error: "chatId dan text wajib diisi." });
  }

  const elapsed = Date.now() - lastSendTimestamp;
  if (elapsed < MIN_SEND_INTERVAL_MS) {
    return res.status(429).json({
      error: `Anti-ban cooldown aktif. Tunggu ${Math.ceil((MIN_SEND_INTERVAL_MS - elapsed) / 1000)} detik lagi.`,
    });
  }

  try {
    await sock.sendPresenceUpdate("composing", chatId);
    const delayMs = 2500 + Math.floor(Math.random() * 3000);
    await sleep(delayMs);
    await sock.sendMessage(chatId, { text: String(text) });
    await sock.sendPresenceUpdate("paused", chatId);
    lastSendTimestamp = Date.now();
    res.json({ status: "sent", chatId });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

app.listen(PORT, HOST, () => {
  console.log(`[WhatsApp Bridge] API lokal berjalan di http://${HOST}:${PORT}`);
  startWhatsApp().catch((err) => console.error("Gagal memulai WhatsApp:", err));
});
