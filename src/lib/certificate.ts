import jsPDF from "jspdf";

interface CertificateData {
  fileName: string;
  score: number;
  date: string;
  scanId: string;
}

export function generateCertificate(data: CertificateData) {
  const doc = new jsPDF();
  const w = doc.internal.pageSize.getWidth();
  const issued = new Date(data.date);

  // === Outer border ===
  doc.setDrawColor(16, 185, 129);
  doc.setLineWidth(2);
  doc.rect(10, 10, w - 20, 277);
  doc.setLineWidth(0.5);
  doc.rect(14, 14, w - 28, 269);

  // === Header / brand ===
  doc.setFontSize(10);
  doc.setTextColor(16, 185, 129);
  doc.text("AUDITREADY AI", w / 2, 28, { align: "center" });

  doc.setFontSize(9);
  doc.setTextColor(120, 120, 120);
  doc.text("AI Compliance & Risk Platform", w / 2, 34, { align: "center" });

  // Decorative line
  doc.setDrawColor(16, 185, 129);
  doc.setLineWidth(1);
  doc.line(50, 40, w - 50, 40);

  // === Title ===
  doc.setFontSize(26);
  doc.setTextColor(30, 30, 30);
  doc.text("Audit Certificate", w / 2, 58, { align: "center" });

  doc.setFontSize(11);
  doc.setTextColor(80, 80, 80);
  doc.text("OFFICIAL COMPLIANCE REPORT", w / 2, 66, { align: "center" });

  // === Body ===
  let y = 85;

  doc.setFontSize(10);
  doc.setTextColor(80, 80, 80);
  doc.text("This certificate confirms that the following document has been", w / 2, y, { align: "center" });
  y += 7;
  doc.text("analyzed and found COMPLIANT with applicable AI governance standards.", w / 2, y, { align: "center" });

  // === Details box ===
  y += 18;
  doc.setFillColor(245, 245, 245);
  doc.roundedRect(30, y, w - 60, 52, 3, 3, "F");

  y += 14;
  const labelX = 40;
  const valueX = 95;

  doc.setFontSize(9);
  doc.setTextColor(120, 120, 120);
  doc.text("Document:", labelX, y);
  doc.setTextColor(30, 30, 30);
  doc.setFont(undefined!, "bold");
  doc.text(data.fileName, valueX, y);

  y += 10;
  doc.setFont(undefined!, "normal");
  doc.setTextColor(120, 120, 120);
  doc.text("Compliance Score:", labelX, y);
  doc.setTextColor(16, 185, 129);
  doc.setFont(undefined!, "bold");
  doc.text(`${data.score} / 100  —  COMPLIANT`, valueX, y);

  y += 10;
  doc.setFont(undefined!, "normal");
  doc.setTextColor(120, 120, 120);
  doc.text("Result:", labelX, y);
  doc.setTextColor(16, 185, 129);
  doc.setFont(undefined!, "bold");
  doc.text("✓  PASS", valueX, y);

  y += 10;
  doc.setFont(undefined!, "normal");
  doc.setTextColor(120, 120, 120);
  doc.text("Date Issued:", labelX, y);
  doc.setTextColor(30, 30, 30);
  doc.text(
    issued.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" }),
    valueX,
    y
  );

  // === Footer ===
  y = 210;
  doc.setDrawColor(200, 200, 200);
  doc.setLineWidth(0.3);
  doc.line(30, y, w - 30, y);
  y += 12;

  doc.setFontSize(8);
  doc.setTextColor(150, 150, 150);
  doc.text(`Certificate ID: ${data.scanId.slice(0, 8).toUpperCase()}`, 30, y);
  y += 5;
  doc.text(`Timestamp: ${issued.toISOString()}`, 30, y);
  y += 5;
  doc.text("Issued by: AuditReady AI Compliance Platform", 30, y);
  y += 5;
  doc.text("This certificate is generated automatically and does not constitute legal advice.", 30, y);

  doc.save(`audit-certificate-${data.fileName.replace(/\s+/g, "-")}.pdf`);
}
