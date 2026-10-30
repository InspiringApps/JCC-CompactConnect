//
//  Application.ts
//  CompactConnect
//
//  Created by InspiringApps on 10/29/2026.
//

import { deleteUndefinedProperties } from '@models/_helpers';
import { serverDateFormat } from '@/app.config';
import { dateDisplay } from '@models/_formatters/date';
import moment from 'moment';
import { StatsigClient } from '@statsig/js-client';

export enum ApplicationType {
    APIT = 'apit',
    TAP = 'tap',
}

export enum ApplicationStatus {
    STARTED = 'started',
    STAFF_REVIEW = 'staff-review',
    FIRST_REVIEW = 'first-review',
    SECOND_REVIEW = 'second-review',
    FINAL_REVIEW = 'final-review',
    COMMITTEE_REVIEW = 'committee-review',
    AWAITING_APPLICANT = 'awaiting-applicant',
    APPROVED = 'approved',
    REJECTED = 'rejected',
    DEACTIVATED = 'deactivated',
}

export enum ApplicantSectionStatus {
    INCOMPLETE = 'incomplete',
    COMPLETE = 'complete',
    NEEDS_ATTENTION = 'needs-attention',
    CONFIRM_DETAILS = 'confirm-details',
}

export enum ReviewSectionStatus {
    PENDING = 'pending',
    AWAITING_APPLICANT = 'awaiting-applicant',
    APPROVED = 'approved',
    REJECTED = 'rejected',
}

export enum ReviewerType {
    FIRST_REVIEWER = 'first-reviewer',
    SECOND_REVIEWER = 'second-reviewer',
    FINAL_REVIEWER = 'final-reviewer',
}

export interface ApplicationReview {
    assignedDate?: string | null;
    reviewer?: {
        id?: string | null,
        firstName?: string | null;
        lastName?: string | null;
    };
    reviewerType: ReviewerType;
    reviewerStatus: ApplicationStatus | ReviewSectionStatus;
    notesForApplicant?: string | null;
    notesForReviewers?: string | null;
}

export enum ApplicationLicenseStatus {
    ACTIVE = 'active',
    INACTIVE = 'inactive',
}

// ========================================================
// =                       Interface                      =
// ========================================================
export interface InterfaceApplicationCreate {
    id?: string | null;
    created?: string | null;
    submitted?: string | null;
    completed?: string | null;
    types?: Array<ApplicationType>;
    isRenewal?: boolean;
    status?: ApplicationStatus;
    reviews?: Array<ApplicationReview>;
    attestations?: Array<string>;
    paymentCompensated?: Array<ApplicationType>;
    personalInformation?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        firstName?: string | null;
        middleName?: string | null;
        lastName?: string | null;
        suffix?: string | null;
        phone?: string | null;
        altPhone?: string | null;
        dob?: string | null;
        ssnLastFour?: string | null;
        npi?: string | null;
        gender?: string | null;
        professionalName?: string | null;
        citizenship?: string | null;
        placeOfBirth?: string | null;
        languages?: Array<string>;
        mailingAddress1?: string | null;
        mailingAddress2?: string | null;
        mailingCity?: string | null;
        mailingState?: string | null;
        mainingZip?: string | null;
    };
    licenseHistory?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        ePassport?: {
            mobilityNumber?: string | null,
            issueDate?: string | null,
        };
        ipc?: {
            mobilityNumber?: string | null,
            issueDate?: string | null,
        };
        licenses?: [
            {
                state?: string | null,
                issueDate?: string | null,
                licenseNumber?: string | null,
                status?: ApplicationLicenseStatus,
            }
        ];
    };
    education?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        nameAtTime?: string | null;
        institution?: string | null;
        city?: string | null;
        state?: string | null;
        degreeType?: string | null;
        program?: string | null;
        department?: string | null;
        conferredDate?: string | null;
        isCompleted?: boolean;
        accreditingBody?: string | null;
        accreditingYear?: string | null;
        isAccreditedByAuthority?: boolean;
        isProgramEquivalent?: boolean;
        accreditingContact?: {
            name?: string | null,
            email?: string | null,
            city?: string | null,
            state?: string | null,
            zip?: string | null,
            phone?: string | null,
            attestations?: Array<string>;
        } | null;
        hasResidence?: boolean;
        transcripts?: Array<{
            filename?: string | null,
            sizeBytes?: number | null,
            downloadUri?: string | null,
        }>;
    };
    conductHistory?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        attestations?: Array<string>;
        convictions?: Array<{
            charge?: string | null,
            location?: string | null,
            date?: string | null,
            type?: string | null,
        }>;
        notes?: string | null;
        documents?: Array<{
            filename?: string | null,
            sizeBytes?: number | null,
            downloadUri?: string | null,
        }>;
    };
    homeState?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        applicationTypes?: Array<{
            applicationType?: ApplicationType,
            state?: string | null,
            startDate?: string | null,
            isActiveMilitary?: boolean;
            militarydocuments?: Array<{
                filename?: string | null,
                sizeBytes?: number | null,
                downloadUri?: string | null,
            }>,
            attestations?: Array<string>;
        }>;
    };
    acknowledgements?: {
        applicantStatus: ApplicantSectionStatus,
        reviewStatus?: ReviewSectionStatus;
        reviews?: Array<ApplicationReview>;
        attestations?: Array<string>;
        signatureName?: string | null;
    };
}

// ========================================================
// =                        Model                         =
// ========================================================
export class Application implements InterfaceApplicationCreate {
    public id? = null;

    constructor(data?: InterfaceApplicationCreate) {
        const cleanDataObject = deleteUndefinedProperties(data);

        Object.assign(this, cleanDataObject);
    }

    // Helper methods
    // @TODO
}

// ========================================================
// =                      Serializer                      =
// ========================================================
export class ApplicationSerializer {
    static fromServer(json: any): Application {
        const applicationData = {
            id: json.id,
        };

        return new Application(applicationData);
    }

    static toServer(applicationModel: Application): any {
        return {
            id: applicationModel.id,
        };
    }
}
