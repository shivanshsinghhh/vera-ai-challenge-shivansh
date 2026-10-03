# Submission checklist

1. Create a new GitHub repository under your own account.
2. Upload this project as-is; do not upload `.venv` or `.env`.
3. In Render, create a Blueprint/Web Service from the repository.
4. Set these environment variables:
   - `TEAM_NAME=Shivansh Kumar Singh`
   - `TEAM_MEMBERS=Shivansh Kumar Singh`
   - `CONTACT_EMAIL=shivansh.kumar.ug23@nsut.ac.in`
5. Deploy and wait for status `Live`.
6. Verify:
   - `/v1/healthz` returns `status: ok`
   - `/v1/metadata` shows your correct details
   - `/docs` lists the required endpoints
7. Run any provided judge simulator against the public URL.
8. Submit the **base URL only**, for example:
   - `https://your-service.onrender.com`
   - not `/v1/healthz`
   - not `/docs`
9. Keep the service live after submission.
