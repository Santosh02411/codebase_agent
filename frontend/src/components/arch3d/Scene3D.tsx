"use client";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import * as THREE from "three";

export type Shape = "sphere" | "box" | "octa" | "core" | "tetra";
export interface SNode { id: string; kind: "cluster" | "file" | "symbol"; x: number; y: number; z: number; r: number; color: string; shape: Shape; label: string; emphasis: 0 | 1 | 2; sub?: string }
export interface SEdge { a: [number, number, number]; b: [number, number, number]; color: string; dashed: boolean; hi: "out" | "in" | "path" | null; key: string }
export interface Hull { id: string; x: number; y: number; z: number; radius: number; color: string; active: boolean; label: string; files: number }
export interface Fly { x: number; y: number; z: number; dist: number; nonce: number }

const HI_COLOR = { out: "#38bdf8", in: "#fbbf24", path: "#4ade80" } as const;

function Instanced({ nodes, shape, onPick, onHover }: { nodes: SNode[]; shape: Shape; onPick: (n: SNode) => void; onHover: (n: SNode | null) => void }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current; if (!mesh) return;
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), c = new THREE.Color(), s = new THREE.Vector3(), p = new THREE.Vector3();
    nodes.forEach((n, i) => {
      const k = n.r * (n.emphasis === 2 ? 1.7 : n.emphasis === 1 ? 1.25 : 1);
      m.compose(p.set(n.x, n.y, n.z), q, s.set(k, k, k)); mesh.setMatrixAt(i, m); mesh.setColorAt(i, c.set(n.color));
    });
    mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [nodes]);
  if (!nodes.length) return null;
  const geo = shape === "box" ? <boxGeometry args={[1.5, 1.5, 1.5]} /> : shape === "octa" ? <octahedronGeometry args={[1.25]} /> : shape === "core" ? <icosahedronGeometry args={[1, 1]} /> : shape === "tetra" ? <tetrahedronGeometry args={[1.3]} /> : <sphereGeometry args={[1, 18, 14]} />;
  return (
    <instancedMesh key={`${shape}-${nodes.length}`} ref={ref} args={[undefined, undefined, nodes.length]}
      onClick={(e) => { e.stopPropagation(); if (e.instanceId !== undefined) onPick(nodes[e.instanceId]); }}
      onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = "pointer"; if (e.instanceId !== undefined) onHover(nodes[e.instanceId]); }}
      onPointerOut={() => { document.body.style.cursor = ""; onHover(null); }}>
      {geo}<meshStandardMaterial roughness={0.42} metalness={0.12} />
    </instancedMesh>
  );
}

function Lines({ edges, dashed, opacity }: { edges: SEdge[]; dashed: boolean; opacity: number }) {
  const ref = useRef<THREE.LineSegments>(null);
  const geo = useMemo(() => {
    const pos = new Float32Array(edges.length * 6), col = new Float32Array(edges.length * 6), c = new THREE.Color();
    edges.forEach((e, i) => { pos.set([...e.a, ...e.b], i * 6); c.set(e.color); col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6); });
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3)); return g;
  }, [edges]);
  useLayoutEffect(() => { if (dashed) ref.current?.computeLineDistances(); }, [geo, dashed]);
  useEffect(() => () => geo.dispose(), [geo]);
  if (!edges.length) return null;
  return <lineSegments ref={ref} geometry={geo}>{dashed ? <lineDashedMaterial vertexColors transparent opacity={opacity} dashSize={0.32} gapSize={0.24} /> : <lineBasicMaterial vertexColors transparent opacity={opacity} />}</lineSegments>;
}

/** Arrowheads (always) and travelling particles (unless reduced motion) on the highlighted edges: the direction of each relationship. */
function Flow({ edges, reduced }: { edges: SEdge[]; reduced: boolean }) {
  const cones = useRef<THREE.InstancedMesh>(null);
  const dots = useRef<THREE.InstancedMesh>(null);
  const list = edges.slice(0, 140);
  useLayoutEffect(() => {
    const mesh = cones.current; if (!mesh) return;
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0), c = new THREE.Color(), s = new THREE.Vector3(1, 1, 1);
    list.forEach((e, i) => {
      const a = new THREE.Vector3(...e.a), b = new THREE.Vector3(...e.b), d = b.clone().sub(a); const len = d.length() || 1; d.normalize();
      q.setFromUnitVectors(up, d); m.compose(a.clone().addScaledVector(d, Math.max(0, len - 0.55)), q, s); mesh.setMatrixAt(i, m); mesh.setColorAt(i, c.set(HI_COLOR[e.hi ?? "out"]));
    });
    mesh.instanceMatrix.needsUpdate = true; if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [list]);
  const tmp = useMemo(() => ({ m: new THREE.Matrix4(), q: new THREE.Quaternion(), s: new THREE.Vector3(1, 1, 1), p: new THREE.Vector3(), c: new THREE.Color() }), []);
  useLayoutEffect(() => { const mesh = dots.current; if (!mesh) return; list.forEach((e, i) => mesh.setColorAt(i, tmp.c.set(HI_COLOR[e.hi ?? "out"]))); if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true; }, [list, tmp]);
  useFrame(({ clock }) => {
    const mesh = dots.current; if (!mesh || reduced) return;
    list.forEach((e, i) => { const t = (clock.elapsedTime * 0.32 + (i * 0.37) % 1) % 1; tmp.p.set(e.a[0] + (e.b[0] - e.a[0]) * t, e.a[1] + (e.b[1] - e.a[1]) * t, e.a[2] + (e.b[2] - e.a[2]) * t); tmp.m.compose(tmp.p, tmp.q, tmp.s); mesh.setMatrixAt(i, tmp.m); });
    mesh.instanceMatrix.needsUpdate = true;
  });
  if (!list.length) return null;
  return (
    <>
      <instancedMesh key={`c${list.length}`} ref={cones} args={[undefined, undefined, list.length]} raycast={() => null}><coneGeometry args={[0.13, 0.4, 8]} /><meshBasicMaterial /></instancedMesh>
      {!reduced && <instancedMesh key={`d${list.length}`} ref={dots} args={[undefined, undefined, list.length]} raycast={() => null}><sphereGeometry args={[0.09, 8, 8]} /><meshBasicMaterial /></instancedMesh>}
    </>
  );
}

function CameraRig({ fly, reduced, controls }: { fly: Fly | null; reduced: boolean; controls: React.RefObject<{ target: THREE.Vector3; update: () => void } | null> }) {
  const { camera } = useThree();
  const goal = useRef<{ pos: THREE.Vector3; look: THREE.Vector3 } | null>(null);
  useEffect(() => {
    const c = controls.current; if (!fly || !c) return;
    const look = new THREE.Vector3(fly.x, fly.y, fly.z);
    const dir = camera.position.clone().sub(c.target); if (dir.lengthSq() < 1e-6) dir.set(0, 0.3, 1); dir.normalize();
    const pos = look.clone().addScaledVector(dir, fly.dist);
    if (reduced) { camera.position.copy(pos); c.target.copy(look); c.update(); } else goal.current = { pos, look };
  }, [fly, reduced, camera, controls]);
  useFrame((_, dt) => {
    const g = goal.current, c = controls.current; if (!g || !c) return;
    const k = 1 - Math.pow(0.0015, dt);
    camera.position.lerp(g.pos, k); c.target.lerp(g.look, k); c.update();
    if (camera.position.distanceTo(g.pos) < 0.05) goal.current = null;
  });
  return null;
}

export interface SceneProps {
  nodes: SNode[]; edges: SEdge[]; hulls: Hull[]; labels: SNode[]; fly: Fly | null; reduced: boolean; theme: "light" | "dark"; startDistance: number;
  onPick: (n: SNode) => void; onHover: (n: SNode | null) => void; onEmpty: () => void;
}

export default function Scene3D({ nodes, edges, hulls, labels, fly, reduced, theme, startDistance, onPick, onHover, onEmpty }: SceneProps) {
  const controls = useRef<{ target: THREE.Vector3; update: () => void } | null>(null);
  const by = (shape: Shape) => nodes.filter((n) => n.shape === shape);
  const solid = useMemo(() => edges.filter((e) => !e.dashed && !e.hi), [edges]);
  const dashed = useMemo(() => edges.filter((e) => e.dashed && !e.hi), [edges]);
  const hi = useMemo(() => edges.filter((e) => e.hi).map((e) => ({ ...e, color: HI_COLOR[e.hi!] })), [edges]);
  const hiSolid = useMemo(() => hi.filter((e) => !e.dashed), [hi]);
  const hiDashed = useMemo(() => hi.filter((e) => e.dashed), [hi]);
  return (
    <Canvas dpr={[1, 2]} camera={{ position: [0, startDistance * 0.25, startDistance], fov: 50, near: 0.1, far: 2000 }} gl={{ antialias: true, alpha: true }} onPointerMissed={onEmpty} aria-label="3D view of the repository">
      <ambientLight intensity={theme === "dark" ? 0.75 : 1.0} />
      <directionalLight position={[20, 30, 15]} intensity={theme === "dark" ? 1.1 : 1.3} />
      <directionalLight position={[-20, -10, -15]} intensity={0.4} />
      <OrbitControls ref={controls as never} makeDefault enableDamping={!reduced} dampingFactor={0.09} rotateSpeed={0.7} zoomSpeed={0.9} panSpeed={0.8} minDistance={1.5} maxDistance={600} />
      <CameraRig fly={fly} reduced={reduced} controls={controls} />
      {hulls.map((h) => (
        <mesh key={h.id} position={[h.x, h.y, h.z]} raycast={() => null}>
          <sphereGeometry args={[h.radius * 1.18, 28, 20]} /><meshBasicMaterial color={h.color} transparent opacity={h.active ? 0.09 : 0.045} depthWrite={false} />
        </mesh>
      ))}
      <Lines edges={solid} dashed={false} opacity={theme === "dark" ? 0.5 : 0.65} />
      <Lines edges={dashed} dashed opacity={theme === "dark" ? 0.5 : 0.65} />
      <Lines edges={hiSolid} dashed={false} opacity={1} />
      <Lines edges={hiDashed} dashed opacity={1} />
      <Flow edges={hi} reduced={reduced} />
      {(["sphere", "box", "octa", "core", "tetra"] as Shape[]).map((s) => <Instanced key={s} shape={s} nodes={by(s)} onPick={onPick} onHover={onHover} />)}
      {labels.map((n) => (
        <Html key={n.id} position={[n.x, n.y + n.r * 1.6 + 0.25, n.z]} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <div className={`whitespace-nowrap rounded-md px-2 py-1 text-[12.5px] font-semibold leading-none shadow-pop ring-1 ring-border ${n.kind === "cluster" ? "bg-primary text-primary-foreground" : "bg-panel text-foreground"}`}>{n.label}{n.sub && <span className="ml-1 opacity-70">{n.sub}</span>}</div>
        </Html>
      ))}
    </Canvas>
  );
}
