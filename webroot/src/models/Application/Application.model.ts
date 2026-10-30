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
    SUBMITTED = 'submitted',
    STAFF_REVIEW = 'staff-review',
    FIRST_REVIEW = 'first-review',
    SECOND_REVIEW = 'second-review',
    FINAL_REVIEW = 'final-review',
    AWAITING_APPLICANT = 'awaiting-applicant',
    APPROVED = 'approved',
    REJECTED = 'rejected',
    DEACTIVATED = 'deactivated',
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
    notesForApplicant?: string | null;
    notesForReviewers?: string | null;
    attestations?: Array<string>;
    paymentCompensated?: Array<ApplicationType>;
    personalInformation?: {
        status?: ApplicationStatus;
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
        status?: ApplicationStatus,
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
        status?: ApplicationStatus,
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
        status?: ApplicationStatus,
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
        status?: ApplicationStatus,
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
        status?: ApplicationStatus,
        notesForApplicant?: string | null;
        notesForReviewers?: string | null;
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
