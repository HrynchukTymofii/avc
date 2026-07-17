import bcrypt from "bcryptjs";
import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";

import { db } from "@/lib/db";

/** NextAuth v4, JWT session strategy (no session table). Google sign-ins are
 * upserted into the users table by the signIn callback; the jwt callback keeps
 * userId/credits/role fresh from the DB on every token refresh. */
export const authOptions: NextAuthOptions = {
  session: {
    strategy: "jwt",
    maxAge: 60 * 24 * 60 * 60, // 60 days
  },
  pages: {
    signIn: "/sign-in",
    error: "/sign-in",
  },
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    }),
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        const user = await db.user.findUnique({
          where: { email: credentials.email.toLowerCase() },
        });
        if (!user?.password) throw new Error("Invalid email or password");

        const valid = await bcrypt.compare(credentials.password, user.password);
        if (!valid) throw new Error("Invalid email or password");

        return { id: user.id, name: user.name, email: user.email, image: user.image };
      },
    }),
  ],
  callbacks: {
    async signIn({ user, account }) {
      if (account?.provider !== "google") return true;

      const email = user.email?.toLowerCase();
      if (!email) return false;

      let dbUser = await db.user.findUnique({ where: { email } });
      if (!dbUser) {
        dbUser = await db.user.create({
          data: {
            email,
            name: user.name || "User",
            image: user.image,
            emailVerified: new Date(), // OAuth users are auto-verified
          },
        });
      }

      const existingAccount = await db.account.findUnique({
        where: {
          provider_providerAccountId: {
            provider: account.provider,
            providerAccountId: account.providerAccountId,
          },
        },
      });
      if (!existingAccount) {
        await db.account.create({
          data: {
            userId: dbUser.id,
            type: account.type,
            provider: account.provider,
            providerAccountId: account.providerAccountId,
            access_token: account.access_token,
            refresh_token: account.refresh_token,
            expires_at: account.expires_at,
            token_type: account.token_type,
            scope: account.scope,
            id_token: account.id_token,
          },
        });
      }
      return true;
    },

    async jwt({ token }) {
      if (!token.email) return token;
      const dbUser = await db.user.findUnique({
        where: { email: token.email.toLowerCase() },
      });
      if (dbUser) {
        token.userId = dbUser.id;
        token.credits = dbUser.credits;
        token.role = dbUser.role;
        token.name = dbUser.name ?? token.name;
        token.picture = dbUser.image ?? token.picture;
      }
      return token;
    },

    async session({ session, token }) {
      if (session.user) {
        session.user.userId = token.userId as string;
        session.user.credits = Number(token.credits ?? 0);
        session.user.role = (token.role as string) ?? "user";
      }
      return session;
    },
  },
};
