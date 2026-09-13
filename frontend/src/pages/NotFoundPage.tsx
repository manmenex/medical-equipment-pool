import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3">
      <p className="text-4xl">🔍</p>
      <p className="text-lg font-semibold">ไม่พบหน้านี้</p>
      <Link to="/" className="text-status-borrowed hover:underline">
        กลับหน้าหลัก
      </Link>
    </div>
  );
}
