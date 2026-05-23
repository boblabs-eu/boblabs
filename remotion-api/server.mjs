/**
 * Bob Manager — Remotion Render API
 *
 * Accepts React/JSX component code + render params,
 * bundles a temporary Remotion project, renders to MP4,
 * and returns the video as base64.
 */

import express from "express";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";

const app = express();
app.use(express.json({ limit: "10mb" }));

const PORT = parseInt(process.env.PORT || "3020", 10);

// ── Health check ─────────────────────────────────
app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "remotion-api" });
});

// ── Render endpoint ──────────────────────────────
app.post("/render", async (req, res) => {
  const {
    code,
    composition_id = "Main",
    width = 1920,
    height = 1080,
    fps = 30,
    duration_in_frames = 120,
    codec = "h264",
    props = {},
  } = req.body;

  if (!code) {
    return res.status(400).json({ error: "Missing 'code' field (React component source)" });
  }

  const jobId = crypto.randomUUID().slice(0, 8);
  const tmpDir = path.join(os.tmpdir(), `remotion-${jobId}`);
  const outFile = path.join(tmpDir, `output.mp4`);

  try {
    // 1. Scaffold temporary Remotion project
    fs.mkdirSync(path.join(tmpDir, "src"), { recursive: true });

    // Write the user-provided component code
    fs.writeFileSync(path.join(tmpDir, "src", "Comp.tsx"), code);

    // Write the Root composition that registers the component
    fs.writeFileSync(
      path.join(tmpDir, "src", "Root.tsx"),
      `import React from "react";
import { Composition } from "remotion";
import { Main } from "./Comp";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="${composition_id}"
      component={Main}
      durationInFrames={${duration_in_frames}}
      fps={${fps}}
      width={${width}}
      height={${height}}
      defaultProps={${JSON.stringify(props)}}
    />
  );
};
`
    );

    // Entry point for bundler
    fs.writeFileSync(
      path.join(tmpDir, "src", "index.ts"),
      `import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";
registerRoot(RemotionRoot);
`
    );

    // tsconfig for the temp project
    fs.writeFileSync(
      path.join(tmpDir, "tsconfig.json"),
      JSON.stringify(
        {
          compilerOptions: {
            target: "ES2018",
            module: "commonjs",
            jsx: "react-jsx",
            strict: false,
            esModuleInterop: true,
            skipLibCheck: true,
            forceConsistentCasingInFileNames: true,
            resolveJsonModule: true,
            outDir: "./dist",
          },
          include: ["src"],
        },
        null,
        2
      )
    );

    // Symlink node_modules from the service install
    const serviceRoot = path.resolve(import.meta.dirname);
    const nmSource = path.join(serviceRoot, "node_modules");
    const nmTarget = path.join(tmpDir, "node_modules");
    if (!fs.existsSync(nmTarget)) {
      fs.symlinkSync(nmSource, nmTarget, "dir");
    }

    console.log(`[${jobId}] Bundling...`);

    // 2. Bundle the project
    const bundled = await bundle({
      entryPoint: path.join(tmpDir, "src", "index.ts"),
      webpackOverride: (config) => config,
    });

    console.log(`[${jobId}] Selecting composition "${composition_id}"...`);

    // 3. Select composition
    const composition = await selectComposition({
      serveUrl: bundled,
      id: composition_id,
      inputProps: props,
    });

    console.log(
      `[${jobId}] Rendering ${composition.width}x${composition.height} @ ${composition.fps}fps, ${composition.durationInFrames} frames...`
    );

    // 4. Render
    await renderMedia({
      composition,
      serveUrl: bundled,
      codec,
      outputLocation: outFile,
      inputProps: props,
    });

    console.log(`[${jobId}] Render complete!`);

    // 5. Read output and return as base64
    const videoBuffer = fs.readFileSync(outFile);
    const b64 = videoBuffer.toString("base64");
    const sizeBytes = videoBuffer.length;

    res.json({
      success: true,
      video_base64: b64,
      size_bytes: sizeBytes,
      composition_id,
      width: composition.width,
      height: composition.height,
      fps: composition.fps,
      duration_in_frames: composition.durationInFrames,
      duration_seconds: composition.durationInFrames / composition.fps,
      codec,
    });
  } catch (err) {
    console.error(`[${jobId}] Render failed:`, err);
    res.status(500).json({
      error: `Render failed: ${err.message}`,
      details: err.stack?.split("\n").slice(0, 5).join("\n"),
    });
  } finally {
    // Cleanup temp directory
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {}
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Remotion API listening on port ${PORT}`);
});
