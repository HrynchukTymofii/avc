import { NextResponse } from "next/server";
import { withAuth } from "next-auth/middleware";

/** Redirects signed-out visitors to /sign-in for every page when auth is on.
 * /api is excluded — backend requests authenticate with their own Bearer token
 * (redirect responses would break fetch calls anyway). */

const authEnabled = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

const protect = withAuth({
  pages: { signIn: "/sign-in" },
});

export default authEnabled ? protect : () => NextResponse.next();

export const config = {
  matcher: [
    "/((?!api|sign-in|sign-up|_next/static|_next/image|favicon.ico|outputs).*)",
  ],
};
