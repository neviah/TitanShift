import { useSchedulerTask } from '../../contexts/SchedulerTaskContext'
import styles from './TaskRunningBanner.module.css'

export function TaskRunningBanner() {
  const { currentTask, isTaskRunning } = useSchedulerTask()

  if (!isTaskRunning || !currentTask) {
    return null
  }

  return (
    <div className={styles.banner}>
      <div className={styles.content}>
        <div className={styles.pulse}></div>
        <div className={styles.text}>
          <div className={styles.title}>Task Running</div>
          <div className={styles.description}>{currentTask.description || 'Processing...'}</div>
        </div>
      </div>
    </div>
  )
}
