import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";

const packageExport = fileURLToPath(
  new URL("../spine_exports/com.yoozoo.jgame.global/", import.meta.url),
);

export default defineConfig({
  publicDir: packageExport,
  server: {
    fs: {
      allow: [fileURLToPath(new URL("..", import.meta.url))],
    },
  },
});
