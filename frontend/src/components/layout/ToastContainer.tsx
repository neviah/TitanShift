import { useToast, type Toast } from '../../contexts/ToastContext'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import styles from './ToastContainer.module.css'

function ToastItem({ toast }: { toast: Toast }) {
  const { removeToast } = useToast()

  const iconMap = {
    info: <Info size={16} />,
    success: <CheckCircle size={16} />,
    warning: <AlertCircle size={16} />,
    error: <AlertCircle size={16} />,
  }

  return (
    <div className={`${styles.toast} ${styles[`toast_${toast.type}`]}`}>
      <div className={styles.toastIcon}>{iconMap[toast.type]}</div>
      <div className={styles.toastMessage}>{toast.message}</div>
      <button
        className={styles.toastClose}
        onClick={() => removeToast(toast.id)}
        aria-label="Close notification"
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const { toasts } = useToast()

  return (
    <div className={styles.container}>
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  )
}
