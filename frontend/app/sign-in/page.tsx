"use client";

import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function SignInForm() {
  const router = useRouter();
  const search = useSearchParams();
  const callbackUrl = search.get("callbackUrl") ?? "/talking-head";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    setBusy(false);
    if (result?.error) {
      setError("Invalid email or password");
      return;
    }
    router.push(callbackUrl);
    router.refresh();
  };

  return (
    <div className="mx-auto max-w-sm space-y-8 pt-10">
      <header className="animate-fade-up text-center">
        <h1 className="text-3xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Welcome back to the studio.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="animate-fade-up space-y-4"
        style={{ "--delay": "0.08s" } as React.CSSProperties}
      >
        <div className="space-y-1.5">
          <label
            htmlFor="email"
            className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
          >
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            disabled={busy}
          />
        </div>
        <div className="space-y-1.5">
          <label
            htmlFor="password"
            className="font-mono text-xs uppercase tracking-widest text-muted-foreground"
          >
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            disabled={busy}
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button
          type="submit"
          size="lg"
          className="w-full font-mono uppercase tracking-widest"
          disabled={busy || !email || !password}
        >
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <div
        className="animate-fade-up space-y-4"
        style={{ "--delay": "0.16s" } as React.CSSProperties}
      >
        <div className="flex items-center gap-3">
          <span className="h-px flex-1 bg-border" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            or
          </span>
          <span className="h-px flex-1 bg-border" />
        </div>
        <Button
          variant="secondary"
          size="lg"
          className="w-full font-mono uppercase tracking-widest"
          onClick={() => signIn("google", { callbackUrl })}
          disabled={busy}
        >
          Continue with Google
        </Button>
        <p className="text-center text-sm text-muted-foreground">
          No account yet?{" "}
          <Link href="/sign-up" className="text-primary underline-offset-2 hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}
