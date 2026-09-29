import { redirect } from "next/navigation";

export default function ReportsIndexPage({ params }: { params: { repositoryId: string } }) {
  redirect(`/r/${params.repositoryId}/reports/summary`);
}
