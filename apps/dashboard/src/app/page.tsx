import Link from "next/link";
import { redirect } from "next/navigation";

// In Phase 1 we redirect directly to dashboard
// Phase 2+ will add proper auth check
export default function Home() {
  redirect("/dashboard");
}
