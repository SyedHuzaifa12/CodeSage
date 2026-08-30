/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pure API client — no server-side secrets, no image domains beyond Google Fonts CSS (self-hosted below).
  eslint: {
    ignoreDuringBuilds: false,
  },
};

export default nextConfig;
