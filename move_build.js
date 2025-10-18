// move_build.js — copia el build de React al backend automáticamente
import fs from "fs";
import path from "path";

const root = path.resolve("./");
const distPath = path.join(root, "frontend", "dist");
const targetPath = path.join(root, "backend", "static");

// Elimina static/ anterior si existe
if (fs.existsSync(targetPath)) {
  fs.rmSync(targetPath, { recursive: true, force: true });
  console.log("🧹 Limpieza de backend/static completa");
}

// Copia el nuevo build
fs.cpSync(distPath, targetPath, { recursive: true });
console.log("✅ Build copiado automáticamente a backend/static");
