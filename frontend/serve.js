const http = require("http");
const fs = require("fs");
const path = require("path");

const host = process.env.HOST || "127.0.0.1";
const port = Number(process.env.PORT || 3000);
const rootDir = __dirname;

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8"
};

function send(response, statusCode, headers, body) {
  response.writeHead(statusCode, headers);
  response.end(body);
}

function resolvePath(urlPath) {
  const pathname = decodeURIComponent((urlPath || "/").split("?")[0]);
  const normalized = pathname === "/" ? "/index.html" : pathname;
  const targetPath = path.normalize(path.join(rootDir, normalized));

  if (!targetPath.startsWith(rootDir)) {
    return null;
  }

  return targetPath;
}

const server = http.createServer((request, response) => {
  const filePath = resolvePath(request.url);

  if (!filePath) {
    send(response, 403, { "Content-Type": "text/plain; charset=utf-8" }, "Forbidden");
    return;
  }

  fs.readFile(filePath, (error, content) => {
    if (!error) {
      const extension = path.extname(filePath).toLowerCase();
      send(
        response,
        200,
        { "Content-Type": mimeTypes[extension] || "application/octet-stream" },
        content
      );
      return;
    }

    if (error.code === "ENOENT") {
      send(response, 404, { "Content-Type": "text/plain; charset=utf-8" }, "Not Found");
      return;
    }

    send(response, 500, { "Content-Type": "text/plain; charset=utf-8" }, "Internal Server Error");
  });
});

server.listen(port, host, () => {
  console.log(`Static frontend available at http://${host}:${port}`);
});
