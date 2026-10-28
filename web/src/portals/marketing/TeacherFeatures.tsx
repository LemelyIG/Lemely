/* Hallmark · pre-emit critique: P4 H4 E4 S5 R4 V4 */
import {
  Files,
  ChartBar,
  UsersThree,
  ChalkboardTeacher,
  ArrowUpRight,
} from '@phosphor-icons/react'
import { teacherFeatures, marketingLinks } from './content'

const icons = {
  mark: Files,
  chart: ChartBar,
  parents: UsersThree,
  class: ChalkboardTeacher,
}
export function TeacherFeatures() {
  return (
    <section className="brand-teachers brand-section">
      <div className="brand-wrap">
        <h2>Built for independent teachers.</h2>
        <div className="brand-teacher-grid">
          {teacherFeatures.map((x, i) => {
            const Icon = icons[x.icon]
            return (
              <article key={x.title}>
                <div className="brand-teacher-icon">
                  <Icon size={30} aria-hidden="true" />
                  <span className="brand-label">0{i + 1}</span>
                </div>
                {x.soon && <span className="brand-coming">COMING SOON</span>}
                <h3>{x.title}</h3>
                <p>{x.description}</p>
              </article>
            )
          })}
        </div>
        <div className="brand-school">
          <p>
            Running a school or department?{' '}
            <span>
              Lemely scales to whole year groups, with admin controls and
              reporting.
            </span>
          </p>
          <a href={marketingLinks.demo}>
            Book a school demo <ArrowUpRight aria-hidden="true" />
          </a>
        </div>
      </div>
    </section>
  )
}
