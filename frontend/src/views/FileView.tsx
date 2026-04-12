import { useEffect, useState } from 'react'
import { fetchWorkspaceFile } from '../api/client'
import styles from './FileView.module.css'

interface FileViewProps {
  selectedFilePath: string | null
}

export function FileView({ selectedFilePath }: FileViewProps) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedFilePath) {
      setContent('')
      setError(null)
      setLoading(false)
      return
    }

    let mounted = true
    setLoading(true)
    setError(null)
    void fetchWorkspaceFile(selectedFilePath)
      .then((file) => {
        if (!mounted) return
        setContent(file.content)
      })
      .catch((err) => {
        if (!mounted) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })

    return () => {
      mounted = false
    }
  }, [selectedFilePath])

  if (!selectedFilePath) {
    return (
      <div className={styles.empty}>
        <p className={styles.title}>Files</p>
        <p className={styles.hint}>Select a file from the left workspace tree.</p>
      </div>
    )
  }

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <h2 className={styles.path}>{selectedFilePath}</h2>
      </div>
      {loading && <p className={styles.hint}>Loading...</p>}
      {error && <p className={`${styles.hint} text-error`}>{error}</p>}
      {!loading && !error && <pre className={styles.content}>{content}</pre>}
    </div>
  )
}