// Authors public/models/argo-float.glb: a painted-aluminium Argo float built from lathe and
// cylinder geometry with PBR materials and a printed label, exported through three.js's
// GLTFExporter inside headless Chromium (the exporter needs browser APIs). Run with the host
// Vite dev server up on port 5174:  node scripts/build-float-model.mjs
import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";

const ORIGIN = process.env.VITE_ORIGIN ?? "http://127.0.0.1:5174";
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`${ORIGIN}/`, { waitUntil: "domcontentloaded" });
const base64 = await page.evaluate(async () => {
  const THREE = await import("/node_modules/three/build/three.module.js");
  const { GLTFExporter } =
    await import("/node_modules/three/examples/jsm/exporters/GLTFExporter.js");
  const group = new THREE.Group();
  group.name = "argo-float";

  const paint = new THREE.MeshPhysicalMaterial({
    name: "hull-paint",
    color: "#f2b61f",
    roughness: 0.42,
    metalness: 0.0,
    clearcoat: 0.4,
    clearcoatRoughness: 0.28,
  });
  const anodised = new THREE.MeshStandardMaterial({
    name: "anodised-black",
    color: "#15181f",
    roughness: 0.38,
    metalness: 0.55,
  });
  const steel = new THREE.MeshStandardMaterial({
    name: "steel",
    color: "#aab2bb",
    roughness: 0.32,
    metalness: 0.85,
  });
  const rubber = new THREE.MeshStandardMaterial({
    name: "rubber",
    color: "#0c0e13",
    roughness: 0.85,
    metalness: 0.0,
  });

  // Hull: a lathe profile with chamfered ends (radius, height), 2.3 m long.
  const hullProfile = [
    [0, -1.2],
    [0.15, -1.2],
    [0.2, -1.17],
    [0.21, -1.12],
    [0.21, 1.0],
    [0.2, 1.05],
    [0.17, 1.08],
    [0, 1.08],
  ].map(([x, y]) => new THREE.Vector2(x, y));
  const hull = new THREE.Mesh(new THREE.LatheGeometry(hullProfile, 64), paint);
  hull.name = "hull";
  group.add(hull);

  // The top end-cap that holds the sensor head and the antenna.
  const capProfile = [
    [0, 1.08],
    [0.2, 1.08],
    [0.2, 1.2],
    [0.15, 1.25],
    [0.15, 1.33],
    [0, 1.33],
  ].map(([x, y]) => new THREE.Vector2(x, y));
  const cap = new THREE.Mesh(new THREE.LatheGeometry(capProfile, 64), anodised);
  cap.name = "end-cap";
  group.add(cap);

  // A black band and the bottom end-cap ring.
  const band = new THREE.Mesh(
    new THREE.CylinderGeometry(0.213, 0.213, 0.07, 64, 1, true),
    rubber,
  );
  band.position.y = -0.82;
  band.name = "band";
  group.add(band);
  const foot = new THREE.Mesh(
    new THREE.CylinderGeometry(0.16, 0.14, 0.06, 48),
    anodised,
  );
  foot.position.y = -1.22;
  foot.name = "foot";
  group.add(foot);

  // Damper plate: the wide thin disc that steadies the float at the surface.
  const plate = new THREE.Mesh(
    new THREE.CylinderGeometry(0.46, 0.46, 0.018, 96),
    steel,
  );
  plate.position.y = 0.92;
  plate.name = "damper-plate";
  group.add(plate);
  for (let i = 0; i < 6; i += 1) {
    const angle = (i / 6) * Math.PI * 2;
    const bolt = new THREE.Mesh(
      new THREE.CylinderGeometry(0.014, 0.014, 0.03, 12),
      anodised,
    );
    bolt.position.set(Math.cos(angle) * 0.33, 0.935, Math.sin(angle) * 0.33);
    group.add(bolt);
  }

  // Sensor head (CTD) with its guard rods and the antenna.
  const ctd = new THREE.Mesh(
    new THREE.CylinderGeometry(0.06, 0.06, 0.2, 32),
    steel,
  );
  ctd.position.set(0.09, 1.42, 0.02);
  ctd.name = "ctd";
  group.add(ctd);
  const ctdCap = new THREE.Mesh(
    new THREE.CylinderGeometry(0.035, 0.06, 0.05, 32),
    anodised,
  );
  ctdCap.position.set(0.09, 1.545, 0.02);
  group.add(ctdCap);
  const tube = new THREE.Mesh(
    new THREE.CylinderGeometry(0.018, 0.018, 0.26, 16),
    steel,
  );
  tube.position.set(-0.08, 1.43, 0.07);
  group.add(tube);
  for (let i = 0; i < 3; i += 1) {
    const angle = (i / 3) * Math.PI * 2 + 0.4;
    const rod = new THREE.Mesh(
      new THREE.CylinderGeometry(0.006, 0.006, 0.34, 8),
      steel,
    );
    rod.position.set(Math.cos(angle) * 0.11, 1.5, Math.sin(angle) * 0.11);
    group.add(rod);
  }
  const boot = new THREE.Mesh(
    new THREE.CylinderGeometry(0.03, 0.04, 0.1, 24),
    rubber,
  );
  boot.position.set(-0.04, 1.37, -0.08);
  group.add(boot);
  const antenna = new THREE.Mesh(
    new THREE.CylinderGeometry(0.011, 0.013, 1.05, 16),
    anodised,
  );
  antenna.position.set(-0.04, 1.93, -0.08);
  antenna.name = "antenna";
  group.add(antenna);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.02, 16, 12), steel);
  tip.position.set(-0.04, 2.46, -0.08);
  tip.name = "antenna-tip";
  group.add(tip);

  // Printed label on the hull, drawn on a canvas and wrapped on a thin curved strip.
  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 512;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#f2b61f";
  ctx.fillRect(0, 0, 1024, 512);
  // The strip's UVs run bottom-up: draw flipped vertically so the print reads upright.
  ctx.translate(0, 256);
  ctx.scale(1, -1);
  ctx.translate(0, -256);
  ctx.fillStyle = "#15181f";
  ctx.fillRect(0, 40, 1024, 10);
  ctx.fillRect(0, 462, 1024, 10);
  ctx.font = "700 170px Figtree, Arial, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("ARGO", 512, 230);
  ctx.font = "500 56px Figtree, Arial, sans-serif";
  ctx.fillText("PROFILING FLOAT · WMO 2902", 512, 320);
  ctx.font = "500 44px Figtree, Arial, sans-serif";
  ctx.fillText("IF FOUND, DO NOT RECOVER · ARGO.UCSD.EDU", 512, 410);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  const label = new THREE.MeshStandardMaterial({
    name: "label",
    map: texture,
    roughness: 0.5,
    metalness: 0.0,
  });
  const strip = new THREE.Mesh(
    new THREE.CylinderGeometry(0.2125, 0.2125, 0.42, 64, 1, true, -0.55, 1.1),
    label,
  );
  strip.position.y = 0.25;
  strip.name = "label";
  group.add(strip);

  group.traverse((object) => {
    if (object.isMesh) {
      object.castShadow = true;
      object.receiveShadow = true;
    }
  });

  const exporter = new GLTFExporter();
  const buffer = await new Promise((resolve, reject) =>
    exporter.parse(group, resolve, reject, { binary: true }),
  );
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i += 1)
    binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
});
await browser.close();
const out = new URL("../public/models/argo-float.glb", import.meta.url);
writeFileSync(out, Buffer.from(base64, "base64"));
console.log(
  "wrote",
  out.pathname,
  Buffer.from(base64, "base64").length,
  "bytes",
);
