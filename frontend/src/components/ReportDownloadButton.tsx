import { useState } from 'react'
import { httpBlob } from '../api/client'

interface ReportDownloadButtonProps {
  reportUrl?: string
}

export function ReportDownloadButton({ reportUrl }: ReportDownloadButtonProps) {
  const [downloading, setDownloading] = useState(false)

  if (!reportUrl) {
    return null
  }

  async function handleDownload() {
    if (!reportUrl) return
    try {
      setDownloading(true)
      const blob = await httpBlob(reportUrl)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'review-report.html'
      link.click()
      URL.revokeObjectURL(url)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <button className="btn-secondary" onClick={handleDownload} disabled={downloading}>
      {downloading ? '下载中…' : '下载报告'}
    </button>
  )
}
