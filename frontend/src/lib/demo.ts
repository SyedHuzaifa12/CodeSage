/**
 * Canned questions shown on the landing-page demo card. They deep-link into
 * the Ask page via `?q=`, so a first-time visitor sees a grounded, cited
 * answer in one click.
 *
 * The questions are only meaningful for the repository they were written
 * for, so they are chosen by the demo's GitHub URL — a differently-seeded
 * demo gets generic questions instead of confidently wrong ones.
 */
const EXPRESS_QUESTIONS: readonly string[] = [
  "How does Express route a request to the right handler?",
  "Where is middleware registered and run?",
  "How does error handling work?",
  "What does app.listen do?",
  "How are views rendered?",
];

const GENERIC_QUESTIONS: readonly string[] = [
  "What does this project do, in a few sentences?",
  "How is the codebase structured?",
  "Where is the main entry point?",
  "How are errors handled?",
  "Where are the tests and how do they run?",
];

export function demoQuestions(githubUrl: string | null | undefined): readonly string[] {
  return /github\.com\/expressjs\/express\/?$/i.test(githubUrl ?? "") ? EXPRESS_QUESTIONS : GENERIC_QUESTIONS;
}
