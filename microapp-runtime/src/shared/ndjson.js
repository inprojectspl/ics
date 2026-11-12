// Newline-delimited JSON framing for the broker <-> runner Unix socket.
// Bounded line length: a peer that floods the socket is cut off instead of
// growing a buffer without limit.
export const MAX_LINE_BYTES = 4 * 1024 * 1024;

export function attachNdjson(socket, onMessage, onProtocolError) {
  let buffer = "";
  socket.setEncoding("utf8");
  socket.on("data", (chunk) => {
    buffer += chunk;
    if (buffer.length > MAX_LINE_BYTES && !buffer.includes("\n")) {
      onProtocolError(new Error("line too long"));
      socket.destroy();
      return;
    }
    let index;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index);
      buffer = buffer.slice(index + 1);
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        onProtocolError(new Error("invalid JSON frame"));
        socket.destroy();
        return;
      }
      if (!message || typeof message !== "object" || typeof message.t !== "string") {
        onProtocolError(new Error("frame without type"));
        socket.destroy();
        return;
      }
      onMessage(message);
    }
  });
  return (message) => {
    if (socket.destroyed) return false;
    return socket.write(`${JSON.stringify(message)}\n`);
  };
}
