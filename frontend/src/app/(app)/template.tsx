"use client";
import { motion } from "framer-motion";

/** Lightweight page transition: a short fade/slide on every navigation. */
export default function Template({ children }: { children: React.ReactNode }) {
  return <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: "easeOut" }} className="h-full">{children}</motion.div>;
}
