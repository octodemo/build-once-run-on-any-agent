// Loopback HTTP server shared by the canvas extension and the preview script.
// Serves the page and its JSON state; binds to 127.0.0.1 only.

import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

export function serve(state, port = 0) {
    return new Promise((resolveServer, rejectServer) => {
        const server = createServer(async (req, res) => {
            try {
                const url = new URL(req.url || "/", "http://127.0.0.1");
                if (url.pathname === "/" || url.pathname === "/index.html") {
                    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
                    res.end(readFileSync(join(HERE, "ui.html"), "utf8"));
                } else if (url.pathname === "/state") {
                    const body = JSON.stringify(await state.snapshot({ force: url.searchParams.get("force") === "1" }));
                    res.writeHead(200, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
                    res.end(body);
                } else {
                    res.writeHead(404, { "content-type": "text/plain" });
                    res.end("Not found");
                }
            } catch (error) {
                res.writeHead(500, { "content-type": "text/plain" });
                res.end(String(error?.message || error));
            }
        });
        server.once("error", rejectServer);
        server.listen(port, "127.0.0.1", () =>
            resolveServer({ server, url: `http://127.0.0.1:${server.address().port}/` }),
        );
    });
}
