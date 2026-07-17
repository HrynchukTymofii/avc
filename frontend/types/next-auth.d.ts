import { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: DefaultSession["user"] & {
      userId: string;
      credits: number;
      role: string;
    };
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    userId?: string;
    credits?: number;
    role?: string;
  }
}
