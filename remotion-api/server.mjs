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

    // A06 — sanitize every interpolated field so a caller-supplied
    // composition_id like ``foo" />){evilJs}({" `` can't break out of
    // the JSX attribute and inject code. We also coerce numerics so a
    // string in ``width`` fails fast instead of producing a malformed
    // <Composition>.
    const safeCompositionId = JSON.stringify(String(composition_id));
    const numericFields = {
      duration_in_frames,
      fps,
      width,
      height,
    };
    const safeNumeric = {};
    for (const [k, v] of Object.entries(numericFields)) {
      const n = Number(v);
      if (!Number.isFinite(n)) {
        return res.status(400).json({ error: `Invalid numeric field: ${k}=${v}` });
      }
      safeNumeric[k] = n;
    }
    const safeProps = JSON.stringify(props ?? {});

    // Write the Root composition that registers the component
    fs.writeFileSync(
      path.join(tmpDir, "src", "Root.tsx"),
      `import React from "react";
import { Composition } from "remotion";
import { Main } from "./Comp";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id={${safeCompositionId}}
      component={Main}
      durationInFrames={${safeNumeric.duration_in_frames}}
      fps={${safeNumeric.fps}}
      width={${safeNumeric.width}}
      height={${safeNumeric.height}}
      defaultProps={${safeProps}}
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

    // R19 — stream the MP4 instead of slurping it twice (raw buffer +
    // base64 string) on the event loop. The response is still JSON for
    // back-compat: we write the envelope header, then pipe the file
    // through a base64 encoder, then close the JSON. Peak memory is now
    // one 64 KiB chunk + ceil(chunk * 4 / 3) of base64 instead of the
    // whole file twice.
    const sizeBytes = fs.statSync(outFile).size;
    const trailer = {
      success: true,
      size_bytes: sizeBytes,
      composition_id,
      width: composition.width,
      height: composition.height,
      fps: composition.fps,
      duration_in_frames: composition.durationInFrames,
      duration_seconds: composition.durationInFrames / composition.fps,
      codec,
    };
    res.setHeader("Content-Type", "application/json");
    // Write the envelope head, then the base64 payload, then the trailer.
    res.write('{"video_base64":"');
    await new Promise((resolve, reject) => {
      const stream = fs.createReadStream(outFile, { highWaterMark: 64 * 1024 });
      // Base64 encodes 3 bytes -> 4 chars. To stream without corruption
      // we buffer a tail of <3 bytes between chunks and only encode the
      // largest 3-multiple prefix; the final flush encodes the tail
      // with the standard padding.
      let tail = Buffer.alloc(0);
      stream.on("data", (chunk) => {
        const combined = tail.length ? Buffer.concat([tail, chunk]) : chunk;
        const aligned = combined.length - (combined.length % 3);
        if (aligned > 0) {
          res.write(combined.subarray(0, aligned).toString("base64"));
        }
        tail = combined.subarray(aligned);
      });
      stream.on("end", () => {
        if (tail.length) {
          res.write(tail.toString("base64"));
        }
        resolve();
      });
      stream.on("error", reject);
    });
    // Close the JSON envelope: end the video_base64 string with `"`,
    // then splice in the trailer object minus its leading `{` so the
    // whole response is a single well-formed JSON object:
    //   {"video_base64":"<base64>","success":true,…}
    const trailerJson = JSON.stringify(trailer);
    res.end('",' + trailerJson.slice(1));
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
